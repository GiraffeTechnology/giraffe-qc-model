"""E2E / abcdYi contract tests — offline (no network required).

Validates:
- QCResult schema satisfies abcdYi event contract (field presence, enum values).
- SKU / tenant identity propagated through SampleItem → QCTask → QCResult FK chain.
- Results are append-only (every run creates a new distinct QCResult row).
- Tier-1 and Tier-2 gating logic correctness.
- Error paths produce clean failure records without crashing.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base, SampleItem, QCTask, QCResult


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def std_image(tmp_path) -> str:
    """Minimal valid PNG image writable by cv2."""
    import cv2
    import numpy as np
    img = np.full((100, 100, 3), 128, dtype=np.uint8)
    p = str(tmp_path / "std.png")
    cv2.imwrite(p, img)
    return p


@pytest.fixture()
def sample_item(db, std_image):
    item = SampleItem(
        sku_id="SKU-ABCDYI-001",
        image_path=std_image,
    )
    db.add(item)
    db.flush()
    return item


class TestAbcdYiContract:
    def test_required_fields_present(self, db, sample_item, std_image):
        from src.qc.comparison import run_comparison
        _, result = run_comparison(db=db, production_image=std_image, sample=sample_item)
        assert result.overall_result in ("pass", "needs_fix", "reject", "unknown")
        assert isinstance(result.similarity_score, float)
        assert result.severity in ("low", "medium", "high", "unknown", None)
        assert result.feedback_zh is not None
        assert result.feedback_en is not None
        assert result.llm_provider is not None
        assert result.model_name is not None
        assert result.elapsed_ms >= 0

    def test_sku_identity_via_fk_chain(self, db, sample_item, std_image):
        from src.qc.comparison import run_comparison
        task, result = run_comparison(db=db, production_image=std_image, sample=sample_item)
        assert task.sample_id == sample_item.id
        loaded = db.get(SampleItem, task.sample_id)
        assert loaded.sku_id == "SKU-ABCDYI-001"
        assert result.task_id == task.id

    def test_results_are_append_only(self, db, sample_item, std_image):
        from src.qc.comparison import run_comparison
        ids = set()
        for _ in range(3):
            _, result = run_comparison(db=db, production_image=std_image, sample=sample_item)
            ids.add(result.id)
        assert len(ids) == 3, "Each run must create a distinct QCResult (append-only semantics)"

    def test_deviations_json_serialisable(self, db, sample_item, std_image):
        import json
        from src.qc.comparison import run_comparison
        _, result = run_comparison(db=db, production_image=std_image, sample=sample_item)
        devs = result.deviations
        if isinstance(devs, str):
            devs = json.loads(devs)
        json.dumps(devs)  # must not raise

    def test_overall_result_valid_enum(self, db, sample_item, std_image):
        from src.qc.comparison import run_comparison
        _, result = run_comparison(db=db, production_image=std_image, sample=sample_item)
        assert result.overall_result in {"pass", "needs_fix", "reject", "unknown"}


class TestTierGating:
    def test_l1_identical_frames_no_change(self):
        import numpy as np
        from src.video.frame_filter import has_changed
        gray = np.zeros((480, 640), dtype=np.uint8)
        changed, _ = has_changed(gray, gray)
        assert not changed

    def test_l1_different_frames_triggers(self):
        import numpy as np
        from src.video.frame_filter import has_changed
        prev = np.zeros((480, 640), dtype=np.uint8)
        curr = np.full((480, 640), 128, dtype=np.uint8)
        changed, _ = has_changed(prev, curr)
        assert changed

    def test_l1_first_frame_always_passes(self):
        import numpy as np
        from src.video.frame_filter import has_changed
        changed, _ = has_changed(None, np.zeros((480, 640), dtype=np.uint8))
        assert changed is True

    def test_l2_score_in_valid_range(self, tmp_path):
        import cv2
        import numpy as np
        from src.video.detector import HybridDetector
        ref = np.full((100, 100, 3), 128, dtype=np.uint8)
        prod = np.full((100, 100, 3), 200, dtype=np.uint8)
        p_ref = str(tmp_path / "ref.png")
        cv2.imwrite(p_ref, ref)
        detector = HybridDetector()
        score, matched_path = detector.score(prod, [p_ref])
        assert 0.0 <= score <= 1.0
        assert matched_path == p_ref


class TestFallbackPaths:
    def test_missing_file_marks_task_failed(self, db, sample_item):
        from src.qc.comparison import run_comparison
        with pytest.raises(RuntimeError):
            run_comparison(
                db=db,
                production_image="/nonexistent/path/image.jpg",
                sample=sample_item,
            )
        task = db.query(QCTask).filter(QCTask.sample_id == sample_item.id).first()
        assert task is not None
        assert task.status == "failed"

    def test_dashscope_provider_no_key_raises_before_network(self, monkeypatch):
        for k in ("DASHSCOPE_API_KEY", "QWEN_API_KEY", "QWEN_TEST_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        from src.llm.dashscope_openai_provider import DashScopeOpenAIProvider
        with pytest.raises((ValueError, ImportError)):
            DashScopeOpenAIProvider()

    def test_boom_provider_fails_cleanly(self, db, sample_item, std_image):
        from src.llm.base import LLMProvider
        from src.qc.comparison import run_comparison

        class BoomProvider(LLMProvider):
            @property
            def provider_name(self): return "boom"
            @property
            def model_name(self): return "boom-1"
            def compare_images(self, *a, **kw):
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            run_comparison(
                db=db,
                production_image=std_image,
                sample=sample_item,
                provider=BoomProvider(),
            )
        task = db.query(QCTask).filter(QCTask.sample_id == sample_item.id).first()
        assert task is not None
        assert task.status == "failed"
