# QC Database — Developer Guide

This guide explains how to run migrations, seed the Artificial Flower Accessory standard, and execute the QC checkpoint workflow tests locally.

---

## Prerequisites

```bash
# Install dependencies with uv
uv sync

# Or with pip
pip install -e ".[dev]"
```

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `QC_DB_URL` | `sqlite:///./giraffe_qc.db` | SQLAlchemy DB URL |

For PostgreSQL:
```bash
export QC_DB_URL="postgresql://user:pass@localhost/giraffe_qc"
```

For SQLite (default):
```bash
# No export needed — SQLite file created automatically
```

---

## Running Migrations

```bash
# Apply all migrations from scratch
alembic upgrade head

# Check current revision
alembic current

# View migration history
alembic history

# Roll back one step
alembic downgrade -1

# Roll back to before QC checkpoint tables
alembic downgrade 001
```

Migrations created:
- `001_initial_schema` — legacy tables (sample_items, qc_tasks, qc_results, video_tasks, capture_records)
- `002_qc_checkpoint_schema` — 18 QC checkpoint tables

### Alternative: `init_db()` (development)

For development without alembic, `init_db()` creates all tables directly:

```python
from src.db.session import init_db
init_db()
```

---

## Seeding the Artificial Flower Accessory Standard

```bash
python scripts/seed_flower_brooch.py
```

This creates:
- `QCProductSku`: `FLOWER-BROOCH-001` — Pearl Rhinestone Artificial Flower Brooch
- `QCStandardVersion`: `v1.0` (active)
- 4 checkpoints: `STAMEN_CENTERING`, `PEARL_COUNT`, `RHINESTONE_COUNT`, `PETAL_INTEGRITY`
- 4 check rules (alignment, count ×2, defect)
- 1 placeholder standard media asset

The seed script is **idempotent** — running it twice is safe.

Custom database:
```bash
QC_DB_URL="postgresql://user:pass@localhost/giraffe_qc" python scripts/seed_flower_brooch.py
```

---

## Running Tests

```bash
# All tests
python -m pytest tests/ -v

# QC checkpoint workflow tests only
python -m pytest tests/test_qc_checkpoint_workflow.py -v

# Single test by name
python -m pytest tests/test_qc_checkpoint_workflow.py::test_inspection_pass -v
```

The QC checkpoint tests use an in-memory SQLite database — no external DB required.

### Test Coverage

| Test | PRD Section | Description |
|---|---|---|
| `test_standard_intake` | 11.1 | Raw message saved, media saved, draft created, no premature approval |
| `test_operator_confirmation` | 11.2 | Confirmation creates v1.0 with 4 checkpoints |
| `test_inspection_pass` | 11.3 | All 4 checkpoints pass → `pass`, coverage 100% |
| `test_inspection_fail` | 11.4 | STAMEN_CENTERING fails → `fail` |
| `test_review_required_occluded_checkpoint` | 11.5 | Occluded PEARL_COUNT → `review_required` |
| `test_incidental_finding_triggers_review` | 11.6 | All pass + major finding → `review_required` |
| `test_no_guess_policy_missing_checkpoint` | 11.7 | Missing checkpoint result → `review_required` (never `pass`) |
| `test_all_18_new_tables_exist` | — | Schema integrity |
| `test_audit_events_written` | — | Audit trail |

---

## Workflow Example (Python)

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.session import init_db
from src.qc import intake_service, confirmation_service, inspection_service

# 1. Setup
engine = create_engine("sqlite:///./giraffe_qc.db", connect_args={"check_same_thread": False})
init_db()
Session = sessionmaker(bind=engine)
db = Session()

# 2. Create SKU
from src.qc import standard_service
sku = standard_service.create_sku(db, sku_code="MY-SKU-001", product_name="My Product")

# 3. Operator sends message
intake = intake_service.create_intake_from_message(
    db, sku_id=sku.id,
    raw_text="Check centering, pearl count 3, rhinestone count 8, no petal cracks.",
    operator_id="op_alice",
)

# 4. Extract requirements (LLM or rule-based)
extracted_json = {
    "product_name": "My Product",
    "checkpoints": [
        {"code": "STAMEN_CENTERING", "name": "Stamen Centering",
         "inspection_method": "alignment", "severity": "major"},
        # ... etc.
    ]
}
intake_service.extract_requirements(db, intake, extracted_json)
intake_service.mark_intake_pending_confirmation(db, intake)

# 5. Operator confirms
confirmation = confirmation_service.confirm_standard_intake(
    db, intake=intake, confirmed_by="op_alice"
)
version = confirmation_service.create_standard_version_from_confirmed_intake(
    db, intake=intake, confirmation=confirmation, version_no="v1.0"
)

# 6. Run inspection
job = inspection_service.create_inspection_job(
    db, sku_id=sku.id, standard_version_id=version.id
)

# 7. Save vision model observations (real or mock)
observations = [{...}]  # one dict per checkpoint
inspection_service.save_checkpoint_results(db, inspection_job=job, results=observations)

# 8. Derive final result
final = inspection_service.derive_final_result(db, job)
print(f"Final result: {final}")

# 9. Generate report
report = inspection_service.generate_final_report(db, job, final)
print(report.report_json)
```

---

## No-Guess Policy

The system enforces the no-guess policy at two levels:

1. **`verification_status` check**: Any checkpoint with `verification_status != "observed"` (e.g. `occluded`, `low_confidence`, `unsupported`) automatically yields `review_required`.
2. **Coverage check**: If the number of checkpoint results is less than `checkpoint_total`, `has_unchecked_checkpoint` is set to `True` and final result is `review_required`.

Production code in `inspection_service.derive_final_result()` never short-circuits to `pass`.

---

## Adding a New Channel Adapter

The intake service is adapter-neutral. To add a WeChat adapter:

1. Parse the incoming WeChat message in your adapter code.
2. Call `intake_service.create_intake_from_message(db, channel_type="wechat", ...)`.
3. If the message contains voice, call `intake_service.transcribe_voice_if_needed(db, message, transcript)`.
4. Continue with the standard extraction and confirmation flow.

No changes to the service layer are needed for new channel types.

---

## File Map

```
src/db/
  qc_checkpoint_models.py   # 18 ORM models
  session.py                # updated: imports qc_checkpoint_models in init_db()

alembic/
  versions/
    001_initial_schema.py   # existing legacy tables
    002_qc_checkpoint_schema.py  # 18 new QC checkpoint tables
  env.py                    # updated: imports all model modules for autogenerate

src/qc/
  intake_service.py         # create_intake_from_message, extract_requirements, ...
  confirmation_service.py   # confirm_standard_intake, create_standard_version_from_confirmed_intake, ...
  standard_service.py       # create_sku, create_standard_version, list_active_checkpoints, ...
  inspection_service.py     # create_inspection_job, save_checkpoint_results, derive_final_result, ...
  human_review_service.py   # create_human_review, override_result, create_training_samples_from_review, ...

scripts/
  seed_flower_brooch.py     # idempotent seed: FLOWER-BROOCH-001 + v1.0 + 4 checkpoints

tests/
  test_qc_checkpoint_workflow.py  # 9 tests covering all 7 PRD scenarios + schema + audit

docs/
  PRD_QC_DB.md              # this PRD
  QC_DB_DEVELOPER_GUIDE.md  # this guide
```
