#!/usr/bin/env python
"""
HISTORICAL DEMO — unrelated to Stage 3 Group A. Do not present this script's
output as Stage 3 Group A/B evidence. Stage 3's Group A/B definitions live in
docs/STAGE3_AB_TESTING_SPEC.md; that spec's real-device entry points are
scripts/jetson_stage3_run_group_a.py and jetson_stage3_run_group_b.py. The
"Capability A" name below predates and has no relationship to that spec.

Core Capability A demo — real end-to-end:
  1. Import standard sample into DB
  2. Compare production image via Qwen vision
  3. Print evidence: HTTP status, elapsed_ms, Qwen response
  4. Verify DB write

Run:
  DASHSCOPE_API_KEY=<key> LLM_ENABLE_REAL_CALLS=true uv run python scripts/run_capability_a_demo.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.session import init_db, SessionLocal
from src.sample_store.manager import import_sample, get_samples
from src.qc.comparison import run_comparison
from src.llm.registry import get_provider

REAL = os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"
KEY  = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY") or ""
print(f"LLM_ENABLE_REAL_CALLS : {REAL}")
print(f"API key prefix        : {KEY[:8]}{'****' if KEY else '(none)'}")
print()

init_db()
db = SessionLocal()

# ── Test group 1: high similarity (same image) ─────────────────────────────
print("=" * 60)
print("TEST 1: high similarity (identical image)")
sample1 = import_sample(db, "SKU-RED-001", "tests/fixtures/red_square.png", "Red square")
task1, result1 = run_comparison(
    db,
    production_image="tests/fixtures/red_square.png",
    sample=sample1,
    requirements="Solid red, no defects",
    provider=get_provider(),
)
print(f"  HTTP status    : {result1.http_status}")
print(f"  elapsed_ms     : {result1.elapsed_ms}")
print(f"  model          : {result1.model_name}")
print(f"  overall_result : {result1.overall_result}")
print(f"  similarity     : {result1.similarity_score:.2f}")
print(f"  severity       : {result1.severity}")
print(f"  feedback_zh    : {result1.feedback_zh[:100]}")
print(f"  DB task id     : {task1.id}, status={task1.status}")
print(f"  DB result id   : {result1.id}")

# ── Test group 2: obvious defect ──────────────────────────────────────────
print()
print("=" * 60)
print("TEST 2: obvious defect (dot on production image)")
sample2 = import_sample(db, "SKU-RED-001", "tests/fixtures/red_square.png", "Red square")
task2, result2 = run_comparison(
    db,
    production_image="tests/fixtures/red_square_with_dot.png",
    sample=sample2,
    requirements="Solid red, no defects, no blemishes",
    notes="Surface must be uniform red",
    provider=get_provider(),
)
print(f"  HTTP status    : {result2.http_status}")
print(f"  elapsed_ms     : {result2.elapsed_ms}")
print(f"  model          : {result2.model_name}")
print(f"  overall_result : {result2.overall_result}")
print(f"  similarity     : {result2.similarity_score:.2f}")
print(f"  severity       : {result2.severity}")
print(f"  feedback_zh    : {result2.feedback_zh[:120]}")
print(f"  deviations     : {result2.deviations}")
print(f"  DB task id     : {task2.id}, status={task2.status}")

# ── Test group 3: blue vs red (completely different) ───────────────────────
print()
print("=" * 60)
print("TEST 3: completely different (blue vs red)")
sample3 = import_sample(db, "SKU-RED-001", "tests/fixtures/red_square.png", "Red square")
task3, result3 = run_comparison(
    db,
    production_image="tests/fixtures/blue_square.png",
    sample=sample3,
    requirements="Solid red, correct colour",
    provider=get_provider(),
)
print(f"  HTTP status    : {result3.http_status}")
print(f"  elapsed_ms     : {result3.elapsed_ms}")
print(f"  overall_result : {result3.overall_result}")
print(f"  similarity     : {result3.similarity_score:.2f}")
print(f"  severity       : {result3.severity}")
print(f"  feedback_zh    : {result3.feedback_zh[:120]}")

# ── DB count verification ─────────────────────────────────────────────────
from src.db.session import engine
from sqlalchemy import text
with engine.connect() as conn:
    task_count   = conn.execute(text("SELECT COUNT(*) FROM qc_tasks")).scalar()
    result_count = conn.execute(text("SELECT COUNT(*) FROM qc_results")).scalar()
    sample_count = conn.execute(text("SELECT COUNT(*) FROM sample_items")).scalar()

print()
print("=" * 60)
print("DB VERIFICATION")
print(f"  sample_items : {sample_count} rows")
print(f"  qc_tasks     : {task_count} rows")
print(f"  qc_results   : {result_count} rows")
print()
print("CAPABILITY A DEMO: COMPLETE")
db.close()
