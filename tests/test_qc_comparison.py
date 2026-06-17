"""Tests for Core Capability A — QC comparison engine (mock mode)."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, SampleItem, QCTask, QCResult
from src.llm.mock_provider import MockProvider
from src.qc.comparison import run_comparison


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_STORE_DIR", str(tmp_path / "samples"))
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample(db, tmp_path):
    src = tmp_path / "std.png"
    src.write_bytes(b"\x00" * 20)
    from src.sample_store.manager import import_sample
    return import_sample(db, "SKU-QC", str(src))


def test_run_comparison_creates_task_and_result(db, sample, tmp_path):
    prod = tmp_path / "prod.png"
    prod.write_bytes(b"\x00" * 20)

    task, result = run_comparison(
        db=db,
        production_image=str(prod),
        sample=sample,
        provider=MockProvider(),
    )
    assert isinstance(task, QCTask)
    assert isinstance(result, QCResult)
    assert task.status == "done"
    assert task.sample_id == sample.id
    assert result.task_id == task.id
    assert result.llm_provider == "mock"
    assert result.http_status == 200


def test_run_comparison_writes_feedback(db, sample, tmp_path):
    prod = tmp_path / "prod2.png"
    prod.write_bytes(b"\x00" * 20)
    _, result = run_comparison(db, str(prod), sample, provider=MockProvider())
    assert isinstance(result.feedback_zh, str)
    assert isinstance(result.feedback_en, str)
    assert result.overall_result in ("pass", "needs_fix", "reject", "unknown")


def test_run_comparison_source_type_video_capture(db, sample, tmp_path):
    prod = tmp_path / "prod3.png"
    prod.write_bytes(b"\x00" * 20)
    task, _ = run_comparison(db, str(prod), sample, provider=MockProvider(), source_type="video_capture")
    assert task.source_type == "video_capture"


def test_run_comparison_default_uses_cv(db, tmp_path):
    """When no provider is given, CVComparator is the default — no LLM needed."""
    import cv2, numpy as np
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = (0, 0, 200)
    std_p  = str(tmp_path / "std_cv.png");  cv2.imwrite(std_p, img)
    prod_p = str(tmp_path / "prod_cv.png"); cv2.imwrite(prod_p, img)
    from src.sample_store.manager import import_sample
    s = import_sample(db, "SKU-CV-DEFAULT", std_p)
    task, result = run_comparison(db, prod_p, s)   # no provider arg
    assert result.llm_provider == "cv"
    assert task.status == "done"
    assert result.overall_result in ("pass", "needs_fix", "reject")


def test_failed_comparison_marks_task_failed(db, sample, tmp_path):
    """A provider that always raises should mark the task as failed."""
    from src.llm.base import LLMProvider

    class FailProvider(LLMProvider):
        @property
        def provider_name(self): return "fail"
        @property
        def model_name(self): return "fail-v1"
        def compare_images(self, *a, **kw):
            raise RuntimeError("intentional failure")

    prod = tmp_path / "prod4.png"
    prod.write_bytes(b"\x00" * 20)
    with pytest.raises(RuntimeError, match="intentional failure"):
        run_comparison(db, str(prod), sample, provider=FailProvider())

    task = db.query(QCTask).order_by(QCTask.id.desc()).first()
    assert task.status == "failed"
