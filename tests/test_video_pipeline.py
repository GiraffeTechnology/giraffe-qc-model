"""Tests for Tier-1/Tier-2 logic and full pipeline in mock mode."""
import numpy as np
import pytest
import cv2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, SampleItem
from src.video.frame_filter import has_changed
from src.video.detector import HybridDetector, above_threshold
from src.video.pipeline import VideoFileSource, run_video_pipeline


# ── Tier-1 frame filter ───────────────────────────────────────────────────

class TestTier1FrameFilter:
    def test_first_frame_always_passes(self):
        frame = np.zeros((100, 100), dtype=np.uint8)
        changed, score = has_changed(None, frame)
        assert changed is True
        assert score == 255.0

    def test_identical_frames_filtered(self, monkeypatch):
        monkeypatch.setenv("TIER1_DIFF_THRESHOLD", "5")
        frame = np.full((100, 100), 128, dtype=np.uint8)
        changed, score = has_changed(frame, frame)
        assert changed is False
        assert score < 5

    def test_different_frames_pass(self, monkeypatch):
        monkeypatch.setenv("TIER1_DIFF_THRESHOLD", "5")
        f1 = np.zeros((100, 100), dtype=np.uint8)
        f2 = np.full((100, 100), 200, dtype=np.uint8)
        changed, score = has_changed(f1, f2)
        assert changed is True
        assert score > 5


# ── Tier-2 hybrid detector ───────────────────────────────────────────────

class TestTier2Detector:
    def setup_method(self):
        self.det = HybridDetector()

    def test_no_samples_returns_zero(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        score, path = self.det.score(frame, [])
        assert score == 0.0
        assert path is None

    def test_identical_image_gives_high_score(self, tmp_path):
        # Create textured sample (not uniform colour)
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:] = (30, 30, 220)
        img[0::20, :] = (255, 255, 255)   # grid lines
        img[:, 0::20] = (255, 255, 255)
        path = str(tmp_path / "sample.png")
        cv2.imwrite(path, img)

        # Frame is the same image scaled up
        frame = cv2.resize(img, (320, 240))
        score, matched = self.det.score(frame, [path])
        assert score > 0.25, f"Expected score > 0.25, got {score}"
        assert matched == path

    def test_unrelated_frame_gives_low_score(self, tmp_path):
        # Red textured sample
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        img[:] = (30, 30, 220)
        img[0::20, :] = (255, 255, 255)
        path = str(tmp_path / "sample2.png")
        cv2.imwrite(path, img)

        # Gray frame — completely different
        frame = np.full((240, 320, 3), 180, dtype=np.uint8)
        score, _ = self.det.score(frame, [path])
        assert score < 0.25, f"Expected score < 0.25 for gray vs red, got {score}"

    def test_above_threshold(self, monkeypatch):
        monkeypatch.setenv("LOCAL_PREFILTER_THRESHOLD", "0.5")
        assert above_threshold(0.6) is True
        assert above_threshold(0.4) is False


# ── VideoFileSource ──────────────────────────────────────────────────────

class TestVideoFileSource:
    def test_reads_frames_from_file(self):
        src = VideoFileSource("tests/fixtures/videos/video_with_target.mp4")
        frames = list(src.frames())
        assert len(frames) > 0
        assert frames[0].index == 0
        assert frames[0].bgr.shape[2] == 3  # BGR channels

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            VideoFileSource("/nonexistent/path.mp4")


# ── Full pipeline in mock mode ────────────────────────────────────────────

@pytest.fixture
def pipeline_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMPLE_STORE_DIR", str(tmp_path / "samples"))
    monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_pipeline_creates_video_task(pipeline_db, tmp_path):
    # Import sample
    from src.sample_store.manager import import_sample
    import cv2, os
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = (30, 30, 220)
    img[0::20, :] = (255, 255, 255)
    sp = str(tmp_path / "std.png")
    cv2.imwrite(sp, img)
    import_sample(pipeline_db, "SKU-PIPE", sp)

    vtask, stats = run_video_pipeline(
        "tests/fixtures/videos/video_with_target.mp4",
        sku_id="SKU-PIPE",
        db=pipeline_db,
    )
    assert vtask.id is not None
    assert vtask.status == "done"
    assert vtask.total_frames > 0
    assert vtask.tier1_filtered >= 0
    assert 0.0 <= vtask.llm_save_ratio <= 1.0


def test_pipeline_no_target_zero_llm_calls(pipeline_db, tmp_path):
    from src.sample_store.manager import import_sample
    import cv2
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = (30, 30, 220)
    img[0::20, :] = (255, 255, 255)
    sp = str(tmp_path / "std2.png")
    cv2.imwrite(sp, img)
    import_sample(pipeline_db, "SKU-NOTARGET", sp)

    _, stats = run_video_pipeline(
        "tests/fixtures/videos/video_no_target.mp4",
        sku_id="SKU-NOTARGET",
        db=pipeline_db,
    )
    # Gray-only video: tier-2 should reject most frames
    assert stats.tier3_comparator_called == 0


def test_pipeline_partial_failure(pipeline_db, tmp_path, monkeypatch):
    """First Tier-3 call succeeds; subsequent raise → 'partial_failed'."""
    # Force all Tier-2 frames into Tier-3 so we get multiple comparator calls
    monkeypatch.setenv("LOCAL_PREFILTER_THRESHOLD", "0.0")

    from src.sample_store.manager import import_sample
    from src.llm.base import LLMProvider, ImageCompareResult
    import cv2

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = (30, 30, 220)
    img[0::20, :] = (255, 255, 255)
    sp = str(tmp_path / "std_pf.png")
    cv2.imwrite(sp, img)
    import_sample(pipeline_db, "SKU-PF", sp)

    calls = {"n": 0}

    class FlakyProvider(LLMProvider):
        @property
        def provider_name(self): return "flaky"
        @property
        def model_name(self): return "flaky-v0"

        def compare_images(self, standard_paths, production_paths, requirements="", notes=""):
            calls["n"] += 1
            if calls["n"] == 1:
                return ImageCompareResult(
                    overall_result="pass", similarity_score=1.0,
                    severity="low", http_status=200, elapsed_ms=0,
                    feedback_zh="ok", feedback_en="ok", deviations=[],
                    provider="flaky", model="flaky-v0", raw_summary="",
                )
            raise RuntimeError("simulated Tier-3 failure")

    vtask, stats = run_video_pipeline(
        "tests/fixtures/videos/video_with_target.mp4",
        sku_id="SKU-PF",
        db=pipeline_db,
        provider=FlakyProvider(),
    )

    # With threshold=0.0 every Tier-2 frame goes to Tier-3 → should be ≥2 calls
    assert stats.tier3_comparator_called >= 2, (
        f"Expected ≥2 Tier-3 calls but got {stats.tier3_comparator_called}"
    )
    assert vtask.status == "partial_failed"
    assert stats.tier3_error_count == stats.tier3_comparator_called - 1


def test_pipeline_raises_for_missing_sku(pipeline_db):
    with pytest.raises(ValueError, match="No active samples"):
        run_video_pipeline(
            "tests/fixtures/videos/video_no_target.mp4",
            sku_id="SKU-DOES-NOT-EXIST",
            db=pipeline_db,
        )


def test_pipeline_stats_persisted_to_db(pipeline_db, tmp_path):
    """VideoTask fields must reflect PipelineStats after completion."""
    from src.sample_store.manager import import_sample
    import cv2

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = (30, 30, 220)
    img[0::20, :] = (255, 255, 255)
    sp = str(tmp_path / "std_stats.png")
    cv2.imwrite(sp, img)
    import_sample(pipeline_db, "SKU-STATS", sp)

    vtask, stats = run_video_pipeline(
        "tests/fixtures/videos/video_with_target.mp4",
        sku_id="SKU-STATS",
        db=pipeline_db,
    )

    # Stats must be reflected in the DB record
    assert vtask.total_frames == stats.total_frames
    assert vtask.tier1_filtered == stats.tier1_filtered
    assert vtask.tier2_processed == stats.tier2_processed
    assert vtask.tier2_passed == stats.tier2_passed
    assert vtask.tier3_llm_called == stats.tier3_comparator_called
    assert vtask.llm_save_ratio == stats.tier3_save_ratio
    assert vtask.completed_at is not None


def test_pipeline_fatal_setup_marks_task_failed(pipeline_db, tmp_path):
    """VideoFileSource failure after vtask creation must set status=failed, not leave it running."""
    from src.sample_store.manager import import_sample
    from src.db.models import VideoTask
    import cv2

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:] = (30, 30, 220)
    img[0::20, :] = (255, 255, 255)
    sp = str(tmp_path / "std_fatal.png")
    cv2.imwrite(sp, img)
    import_sample(pipeline_db, "SKU-FATAL", sp)

    with pytest.raises(FileNotFoundError):
        run_video_pipeline(
            "/nonexistent/video_does_not_exist.mp4",
            sku_id="SKU-FATAL",
            db=pipeline_db,
        )

    # The task that was created must be marked failed, not stuck in running
    tasks = pipeline_db.query(VideoTask).filter(VideoTask.sku_id == "SKU-FATAL").all()
    assert len(tasks) == 1
    assert tasks[0].status == "failed", (
        f"Expected status='failed' but got {tasks[0].status!r} — "
        "task was left stuck in 'running' after fatal setup error"
    )
