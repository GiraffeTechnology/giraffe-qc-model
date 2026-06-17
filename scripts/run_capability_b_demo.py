#!/usr/bin/env python
"""
Core Capability B demo — three-tier video pipeline.

Run (mock mode):
  uv run python scripts/run_capability_b_demo.py

Run (real Qwen):
  DASHSCOPE_API_KEY=<key> LLM_ENABLE_REAL_CALLS=true uv run python scripts/run_capability_b_demo.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.session import init_db, SessionLocal, engine
from src.sample_store.manager import import_sample, get_samples
from src.video.pipeline import run_video_pipeline
from sqlalchemy import text

REAL = os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"
KEY  = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or ""
print(f"LLM_ENABLE_REAL_CALLS : {REAL}")
print(f"API key prefix        : {KEY[:8]}{'****' if KEY else '(none — mock mode)'}")
print()

init_db()
db = SessionLocal()

# Register sample for SKU-RED-001 (same as Capability A)
samples = get_samples(db, "SKU-RED-001")
if not samples:
    s = import_sample(db, "SKU-RED-001", "tests/fixtures/red_square.png", "Red square standard")
    print(f"Imported sample: id={s.id}, path={s.image_path}")
else:
    print(f"Using existing sample: id={samples[0].id}")

# ── VIDEO 1: contains target ───────────────────────────────────────────────
print()
print("=" * 60)
print("VIDEO 1: video_with_target.mp4 (50 frames, target appears ~frames 20-30)")
t0 = time.time()
vtask1, stats1 = run_video_pipeline(
    "tests/fixtures/videos/video_with_target.mp4",
    sku_id="SKU-RED-001",
    requirements="Solid red, no defects",
    db=db,
)
elapsed1 = time.time() - t0

print(f"  Total frames sampled  : {stats1.total_frames}")
print(f"  Tier-1 filtered       : {stats1.tier1_filtered}  (no change, discarded)")
print(f"  Tier-2 processed      : {stats1.tier2_processed}  (sent to ORB matcher)")
print(f"  Tier-2 passed         : {stats1.tier2_passed}   (above ORB threshold → Tier-3)")
print(f"  Tier-3 LLM called     : {stats1.tier3_llm_called}")
print(f"  LLM save ratio        : {stats1.llm_save_ratio:.1%}  (vs calling LLM every frame)")
print(f"  Total elapsed         : {elapsed1:.1f}s")
print(f"  VideoTask id          : {vtask1.id}, status={vtask1.status}")
if stats1.captures:
    print(f"  Captures:")
    for c in stats1.captures:
        print(f"    frame={c['frame_index']:4d}  orb={c['orb_score']:.3f}  qc_task={c['qc_task_id']}")
else:
    print("  No frames captured (target not detected above threshold)")

# ── VIDEO 2: no target ────────────────────────────────────────────────────
print()
print("=" * 60)
print("VIDEO 2: video_no_target.mp4 (50 frames, random noise — no target)")
t0 = time.time()
vtask2, stats2 = run_video_pipeline(
    "tests/fixtures/videos/video_no_target.mp4",
    sku_id="SKU-RED-001",
    requirements="Solid red, no defects",
    db=db,
)
elapsed2 = time.time() - t0

print(f"  Total frames sampled  : {stats2.total_frames}")
print(f"  Tier-1 filtered       : {stats2.tier1_filtered}")
print(f"  Tier-2 processed      : {stats2.tier2_processed}")
print(f"  Tier-2 passed         : {stats2.tier2_passed}   (should be 0 or very low)")
print(f"  Tier-3 LLM called     : {stats2.tier3_llm_called}  (should be 0)")
print(f"  LLM save ratio        : {stats2.llm_save_ratio:.1%}")
print(f"  Total elapsed         : {elapsed2:.1f}s")

# ── DB verification ─────────────────────────────────────────────────────────
print()
print("=" * 60)
print("DB VERIFICATION")
with engine.connect() as conn:
    vtasks = conn.execute(text("SELECT COUNT(*) FROM video_tasks")).scalar()
    caps   = conn.execute(text("SELECT COUNT(*) FROM capture_records")).scalar()
    tasks  = conn.execute(text("SELECT COUNT(*) FROM qc_tasks WHERE source_type='video_capture'")).scalar()
    results= conn.execute(text("SELECT COUNT(*) FROM qc_results")).scalar()
print(f"  video_tasks              : {vtasks}")
print(f"  capture_records          : {caps}")
print(f"  qc_tasks (video_capture) : {tasks}")
print(f"  qc_results               : {results}")

# ── LLM call saving comparison ──────────────────────────────────────────────
total_frames = stats1.total_frames + stats2.total_frames
total_llm    = stats1.tier3_llm_called + stats2.tier3_llm_called
print()
print("=" * 60)
print("PIPELINE SAVING SUMMARY")
print(f"  Total frames across both videos : {total_frames}")
print(f"  If LLM called every frame       : {total_frames} calls")
print(f"  Actual LLM calls (Tier-3)       : {total_llm}")
print(f"  LLM calls saved                 : {total_frames - total_llm}  ({(total_frames - total_llm)/total_frames:.1%})")
print()
print("CAPABILITY B DEMO: COMPLETE")
db.close()
