"""
Three-tier video processing pipeline.

Tier 1 — Frame differencing (every frame, O(pixels), ~1ms):
  Skip frames with no new content (static/unchanged).

Tier 2 — ORB local feature matching (changed frames only, ~10ms):
  Compare against sample library.  Only frames above LOCAL_PREFILTER_THRESHOLD
  proceed to Tier 3.

Tier 3 — CV comparator (high-confidence frames only, ~20ms):
  Reuses Core Capability A's run_comparison() with CVComparator by default.
  Pass an LLMProvider to run_video_pipeline() to use Qwen/OpenAI instead.

VideoTask.status values:
  "running"        — in progress
  "done"           — completed, all Tier-3 calls succeeded (or none triggered)
  "partial_failed" — completed, but ≥1 Tier-3 call raised an exception
  "failed"         — completed, all Tier-3 calls raised, or fatal setup error
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import cv2
import numpy as np
from sqlalchemy.orm import Session

from src.config import capture_dir, video_sample_fps
from src.db.models import VideoTask, CaptureRecord, SampleItem
from src.db.session import SessionLocal
from src.qc.comparison import run_comparison
from src.sample_store.manager import get_samples
from src.video.detector import ORBDetector, LocalDetector, above_threshold
from src.video.frame_filter import has_changed

logger = logging.getLogger(__name__)


@dataclass
class FrameTuple:
    index: int
    timestamp_ms: int
    bgr: np.ndarray


class VideoFileSource:
    """Reads frames from a video file, sampling at VIDEO_SAMPLE_FPS."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {path}")

    @property
    def fps(self) -> float:
        return self._cap.get(cv2.CAP_PROP_FPS) or 25.0

    def frames(self) -> Iterator[FrameTuple]:
        native_fps = self.fps
        sample_fps = video_sample_fps()
        step = max(1, int(native_fps / sample_fps)) if sample_fps > 0 else 1
        idx  = 0
        while True:
            ret, frame = self._cap.read()
            if not ret:
                break
            if idx % step == 0:
                ts_ms = int(self._cap.get(cv2.CAP_PROP_POS_MSEC))
                yield FrameTuple(index=idx, timestamp_ms=ts_ms, bgr=frame)
            idx += 1
        self._cap.release()


@dataclass
class PipelineStats:
    total_frames: int = 0
    tier1_filtered: int = 0            # dropped by diff check
    tier2_processed: int = 0           # sent to detector
    tier2_passed: int = 0              # above threshold → Tier 3
    tier3_comparator_called: int = 0   # Tier-3 attempts (CV or LLM)
    tier3_error_count: int = 0         # Tier-3 failures
    captures: list[dict] = field(default_factory=list)

    # ── Backward-compatible aliases ──────────────────────────────────────────
    @property
    def tier3_llm_called(self) -> int:
        return self.tier3_comparator_called

    @property
    def tier3_save_ratio(self) -> float:
        if self.total_frames == 0:
            return 0.0
        return 1.0 - self.tier3_comparator_called / self.total_frames

    @property
    def llm_save_ratio(self) -> float:
        return self.tier3_save_ratio


def run_video_pipeline(
    video_path: str,
    sku_id: str,
    requirements: str = "",
    notes: str = "",
    db: Session | None = None,
    detector: LocalDetector | None = None,
    provider=None,
) -> tuple[VideoTask, PipelineStats]:
    """
    Process a video file through the three-tier pipeline.

    Args:
        provider: LLMProvider instance for Tier-3, or None to use CVComparator.

    Returns:
        (VideoTask, PipelineStats) — VideoTask committed to DB.
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()

    cap_dir = capture_dir()
    cap_dir.mkdir(parents=True, exist_ok=True)
    det = detector or ORBDetector()

    samples: list[SampleItem] = get_samples(db, sku_id)
    if not samples:
        raise ValueError(f"No active samples for SKU {sku_id!r}")
    sample_paths   = [s.image_path for s in samples]
    primary_sample = samples[0]

    vtask = VideoTask(
        video_path=video_path,
        sku_id=sku_id,
        status="running",
        created_at=datetime.now(timezone.utc),
    )
    db.add(vtask)
    db.commit()
    db.refresh(vtask)

    stats = PipelineStats()
    try:
        source = VideoFileSource(video_path)
    except FileNotFoundError:
        vtask.status = "failed"
        vtask.completed_at = datetime.now(timezone.utc)
        db.commit()
        if own_db:
            db.close()
        raise
    prev_gray: np.ndarray | None = None

    for ft in source.frames():
        stats.total_frames += 1
        gray = cv2.cvtColor(ft.bgr, cv2.COLOR_BGR2GRAY)

        # ── Tier 1: frame differencing ──────────────────────────────────────
        changed, _ = has_changed(prev_gray, gray)
        prev_gray  = gray
        if not changed:
            stats.tier1_filtered += 1
            continue

        # ── Tier 2: detector ────────────────────────────────────────────────
        stats.tier2_processed += 1
        orb_score, _ = det.score(ft.bgr, sample_paths)
        if not above_threshold(orb_score):
            continue

        # ── Tier 3: comparator ──────────────────────────────────────────────
        stats.tier2_passed           += 1
        stats.tier3_comparator_called += 1

        cap_path = cap_dir / f"vtask{vtask.id}_frame{ft.index}.png"
        cv2.imwrite(str(cap_path), ft.bgr)

        qc_task_id = None
        try:
            qc_task, _ = run_comparison(
                db=db,
                production_image=str(cap_path),
                sample=primary_sample,
                requirements=requirements,
                notes=notes,
                provider=provider,
                source_type="video_capture",
            )
            qc_task_id = qc_task.id
        except Exception as exc:
            stats.tier3_error_count += 1
            logger.warning("Tier-3 failed for frame %d: %s", ft.index, exc)

        rec = CaptureRecord(
            video_task_id=vtask.id,
            frame_index=ft.index,
            frame_timestamp_ms=ft.timestamp_ms,
            frame_path=str(cap_path),
            tier2_score=orb_score,
            qc_task_id=qc_task_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(rec)
        db.commit()

        stats.captures.append({
            "frame_index":  ft.index,
            "timestamp_ms": ft.timestamp_ms,
            "orb_score":    orb_score,
            "qc_task_id":   qc_task_id,
        })

    # ── Determine final status ───────────────────────────────────────────────
    if stats.tier3_error_count == 0:
        final_status = "done"
    elif stats.tier3_error_count == stats.tier3_comparator_called:
        final_status = "failed"       # every Tier-3 attempt failed
    else:
        final_status = "partial_failed"

    vtask.status           = final_status
    vtask.completed_at     = datetime.now(timezone.utc)
    vtask.total_frames     = stats.total_frames
    vtask.tier1_filtered   = stats.tier1_filtered
    vtask.tier2_processed  = stats.tier2_processed
    vtask.tier2_passed     = stats.tier2_passed
    vtask.tier3_llm_called = stats.tier3_comparator_called
    vtask.llm_save_ratio   = stats.tier3_save_ratio
    db.commit()
    db.refresh(vtask)

    if own_db:
        db.close()

    return vtask, stats
