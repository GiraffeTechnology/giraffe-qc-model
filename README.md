# giraffe-qc-model

Quality-control model for manufacturing inspection. Compares production images against standard samples using a multi-tier CV pipeline, with optional LLM escalation.

## Architecture

```
Core Capability A — Image QC
  CVComparator (default)  →  colour + structure + ORB + pixel-diff
  Qwen VL / OpenAI       →  optional LLM escalation (requires API key)

Core Capability B — Video QC
  Tier 1: frame differencing   (O(pixels), ~1 ms)
  Tier 2: ORB + HSV matching   (~10 ms, filters ~80–95% of frames)
  Tier 3: CVComparator / LLM   (~20 ms, high-confidence frames only)
```

## Quick Start

```bash
uv sync
# Run all tests
uv run pytest tests/ -v
# Run Capability A demo
uv run python scripts/run_capability_a_demo.py
# Run Capability B demo (video pipeline)
uv run python scripts/run_capability_b_demo.py
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SAMPLE_STORE_DIR` | `data/samples` | Directory where sample images are stored |
| `CAPTURE_DIR` | `data/captures` | Directory for video frame captures |
| `VIDEO_SAMPLE_FPS` | `2` | Frames per second to sample from video |
| `TIER1_DIFF_THRESHOLD` | `5` | Mean pixel diff below this is filtered (Tier 1) |
| `LOCAL_PREFILTER_THRESHOLD` | `0.25` | ORB/HSV score below this skips Tier 3 |
| `LLM_ENABLE_REAL_CALLS` | `false` | Set `true` to enable real LLM API calls |
| `LLM_PROVIDER` | `cv` | Provider: `cv`, `mock`, `qwen`, `openai` |
| `DASHSCOPE_API_KEY` / `QWEN_API_KEY` | — | API key for Qwen (DashScope) |

All variables are read at call time — no process restart needed.

## LLM Provider Selection

```
get_provider()               → CVComparator (default, no API key needed)
get_provider("cv")           → CVComparator
get_provider("mock")         → MockProvider (deterministic, for testing)
LLM_ENABLE_REAL_CALLS=false  → any LLM name silently falls back to CV
LLM_ENABLE_REAL_CALLS=true + DASHSCOPE_API_KEY=<key>  → QwenProvider
LLM_ENABLE_REAL_CALLS=true + no key                   → ValueError (operator error)
```

## CVComparator

Built-in visual engine — no LLM, no API key, runs fully offline.

Scoring (when ORB applicable): `0.25·colour + 0.30·structure + 0.25·ORB + 0.20·pixel`

| Verdict | Condition |
|---|---|
| `pass` | similarity ≥ 0.86 |
| `needs_fix` | 0.60 ≤ similarity < 0.86, or defect area 1.5–7% |
| `reject` | similarity < 0.60, or colour mismatch, or defect area ≥ 7% |

## Database Models

| Table | Purpose |
|---|---|
| `sample_items` | Standard-photo library per SKU |
| `qc_tasks` | One inspection task per production image |
| `qc_results` | Structured result from each task |
| `video_tasks` | Video processing job with tier statistics |
| `capture_records` | Frames auto-captured from video |

## Sample Store

```python
from src.sample_store.manager import import_sample, get_samples, list_all_skus

item = import_sample(db, "SKU-001", "/path/to/photo.png", product_name="Red Fabric")
samples = get_samples(db, "SKU-001")   # active only, newest first
skus = list_all_skus(db)
```

Each import generates a unique destination filename (`{sku}_{timestamp}_{uuid}_{filename}`) to prevent overwriting previous samples.

## Running QC

```python
from src.qc.comparison import run_comparison

qc_task, result = run_comparison(
    db=session,
    production_image="/path/to/production.png",
    sample=sample_item,
    requirements="Solid red, no defects",
)
print(result.overall_result)   # "pass" | "needs_fix" | "reject" | "unknown"
print(result.similarity_score) # 0.0–1.0
print(result.feedback_en)
```

## Video Pipeline

```python
from src.video.pipeline import run_video_pipeline

vtask, stats = run_video_pipeline(
    "path/to/video.mp4",
    sku_id="SKU-001",
    db=session,
)
print(vtask.status)                    # "done" | "partial_failed" | "failed"
print(stats.tier3_comparator_called)  # frames that reached Tier 3
print(stats.tier3_save_ratio)         # fraction of frames skipped by Tier 1+2
```

## Security

- API keys: never logged in full; logs show first 8 chars + `****`
- Sample paths: SKU IDs are sanitised (`[^\w\-]` → `_`) to prevent path traversal
- No SQL string interpolation; all queries use SQLAlchemy ORM or parameterised text
