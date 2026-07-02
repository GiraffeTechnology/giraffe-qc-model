# Qualification, Shadow Mode &amp; Accuracy Gate (PR 27)

The qualification harness converts production confidence from a code claim into a
**measured, auditable report**. Only a supervisor-approved report that meets the
false-pass / false-fail / sample-count thresholds unlocks L3 `controlled_active`.

> Product rule: **No qualification, no `controlled_active`. No shadow-mode
> evidence, no qualification. No acceptable false-pass rate, no
> `controlled_active`.** False pass is critical (default max false-pass rate = 0).

## Flow

```
Supervisor creates a qualification dataset (SKU / station / Training Pack)
→ adds real reference/positive/defect/boundary/capture-artifact samples,
  each with a ground-truth human label (pass | fail)
→ run: the production-eligible VLM predicts each sample; the system computes a
  per-detection-point confusion matrix + false-pass/false-fail rates
→ qualification report (draft) with per-point meets_thresholds
→ supervisor approves (identity required; report immutable once approved)
→ readiness controlled_active_qualification passes → L3 unlockable
```

## Metrics &amp; thresholds

Per detection point:

- `false_pass` = model predicted **pass** on a **fail** sample (critical).
- `false_fail` = model predicted **fail** on a **pass** sample.
- `review_required` / `capture_retry_required` / `measurement_required` →
  counted as `indeterminate` (escalated, never a confident pass).

`meets_thresholds` requires all of (env-configurable, conservative defaults):

```
QC_MAX_FALSE_PASS_RATE_L3=0.0
QC_MAX_FALSE_FAIL_RATE_L3=0.05
QC_MIN_QUALIFICATION_SAMPLES_PER_POINT=30
QC_MIN_DEFECT_SAMPLES_PER_POINT=10
QC_MIN_BOUNDARY_SAMPLES_PER_POINT=5
```

Exceeding the false-pass threshold (or any minimum) makes the report fail; a
failing report **cannot be approved**, and L3 stays blocked.

## Provider

Qualification runs use the **production-eligible** server VLM (PR 26) and are
**server-side only** (`tablet_mnn` refused). Mock/fake/stub/skeleton providers
cannot run qualification.

## Shadow mode (L1)

`record_shadow_observation` stores model disposition vs. human decision and
whether they agree; `shadow_report` aggregates the disagreement rate. Shadow
mode **never affects pass/reject** and never unlocks L3 on its own.

## Readiness integration

The `controlled_active_qualification` check (PR 24) now passes iff an approved,
threshold-meeting `QualificationReport` exists for the pack+tenant. Combined with
L2 readiness + L3 coverage, this is what makes `controlled_active_allowed` true.

## API

```
POST /api/qc/training-packs/{id}/qualification-datasets
POST /api/qc/qualification-datasets/{dataset_id}/samples
POST /api/qc/qualification-datasets/{dataset_id}/run
GET  /api/qc/qualification-runs/{run_id}
GET  /api/qc/qualification-runs/{run_id}/report
POST /api/qc/qualification-reports/{report_id}/approval
POST /api/qc/training-packs/{id}/shadow-observations
GET  /api/qc/training-packs/{id}/shadow-report
```

UI: `/admin/qc-model/training-packs/{id}/qualification`.

## Migration

`alembic/versions/015_qc_qualification.py` adds the qualification/shadow tables.
Verified `up → down → up` clean. `QualificationApproval` is append-only; an
approved report is immutable.

## Out of scope

- False-pass **incident** response &amp; requalification loop is PR 28.
