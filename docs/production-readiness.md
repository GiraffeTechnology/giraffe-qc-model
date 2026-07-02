# Production Readiness Gate (PR 24 fix)

This document describes the hardened Training Pack readiness gate. It is the
gate that decides whether a Training Pack may enter `exam_ready`,
`production_assisted` (L2), or `controlled_active` (L3).

> **Mocked tests prove workflow only, not production visual accuracy.**
> Production Assisted Mode requires a human final decision. Controlled Active
> Mode requires qualification and false-pass monitoring (a later PR).

## Production modes

| Mode | Meaning | Gate |
| --- | --- | --- |
| L0 demo/mock | mock provider, synthetic fixtures | not gated; no production claim |
| `exam_ready` | QC knowledge complete | all knowledge checks pass, incl. approved/applied visual memory |
| `production_assisted` (L2) | assisted factory use, human-final | exam_ready + coverage + production-eligible provider + pseudo/capture closure |
| `controlled_active` (L3) | scoped auto pass/reject | production_assisted + stricter coverage + **qualification report** (not yet available → fails closed) |

`on_trial` maps to an L1/L2 trial gate (knowledge-complete). The legacy `active`
status maps to L3 `controlled_active` and is **no longer** a general
production-safe alias — it requires qualification.

## Readiness checks

Knowledge-complete (block `exam_ready`):
`source_documents_reviewed`, `detection_points_confirmed`,
`physical_measurement_boundaries_confirmed`,
`rule_verification_requirements_confirmed`, `visual_rules_approved`,
**`visual_rule_memory_required`**, `no_unresolved_questions` (waivable),
`no_unreviewed_conflicts`, `no_pending_high_risk_pseudo_defects`,
`no_pending_critical_defect_rules`.

Additional for L2 `production_assisted`:
`sample_coverage_sufficient`, **`production_eligible_provider`**,
`pseudo_defect_rules_closed`, `capture_artifact_rules_closed`.

Additional for L3 `controlled_active`:
`sample_coverage_sufficient_l3`, **`controlled_active_qualification`**.

### `visual_rule_memory_required` (§4.1)

For every confirmed detection point with `checkpoint_category ∈
{visual_defect, rule_verification}` and `ai_role ∈ {primary_visual_judge,
information_extraction, assisted_visual_judge}`, there must be at least one of:
an approved/applied `VisualRuleMemory`, or a `QCConfirmedVisualRule`, for the
same `training_pack_id + detection_point_code`. A completed sample-learning job
is **not** sufficient.

### `production_eligible_provider` (§4.3)

Approved/applied visual memory must trace to a `SampleLearningJob.provider` that
is **not** `mock` / `fake` / `stub` / `skeleton` (and must have a traceable
provider). Mock-derived memory can satisfy L0 only; it never satisfies L2/L3.

### Sample coverage (§4.2)

L2 requires ≥1 reviewed positive group and ≥1 reviewed defect/boundary group.
L3 per-type minimums are conservative and environment-configurable:

```
QC_READINESS_MIN_REFERENCE_GROUPS=1
QC_READINESS_MIN_POSITIVE_GROUPS=2
QC_READINESS_MIN_DEFECT_GROUPS=1
QC_READINESS_MIN_BOUNDARY_GROUPS=1
QC_READINESS_MIN_CAPTURE_ARTIFACT_GROUPS=0
```

### Pseudo-defect / capture-artifact closure (§4.7)

Approving a `VisualRuleMemory` closes its associated `PseudoDefectRule` /
`CaptureArtifactRule` (→ `approved`); applying it marks them `applied`;
rejecting closes them `rejected`. Any still-`proposed` pseudo-defect or
capture-artifact rule blocks L2/L3 readiness.

## Unified ownership (§4.4)

`src/qc_model/training_pack/ownership.py` derives a pack's tenant ownership from
every tenant-scoped table that references it (`QCSourceDocument`,
`QCLearningJob`, `RuleAuthoringJob`, `SampleGroup`, `SampleLearningJob`,
`VisualRuleMemory`, `QCConfirmedVisualRule`, `PseudoDefectRule`,
`CaptureArtifactRule`, `QCReadinessWaiver`). Unknown / cross-tenant packs fail
closed. Ingestion and readiness both use this single resolver.

## Target-mode API (§4.8)

```
GET /api/qc/training-packs/{id}/readiness?target_mode=production_assisted
GET /api/qc/training-packs/{id}/readiness?target_mode=controlled_active
```

Response includes `target_mode`, `exam_ready_allowed`,
`production_assisted_allowed`, `controlled_active_allowed`, `blocking_checks`,
and `checks` (plus legacy `active_allowed` / `on_trial_allowed`).

## Migration note

The PR24 fix adds no new tables or columns — it reuses existing models and
statuses. No new Alembic migration is required; migrations 008–012 are
unchanged.

## Known limitations / production blockers

- **L3 controlled active is not attainable yet**: it fails closed on
  `controlled_active_qualification` until the qualification harness (a later PR)
  exists. This is intentional.
- Mocked tests prove the workflow only. Real visual accuracy requires a real
  VLM provider path and qualification (later PRs).
- Production inspection sessions / evidence packets / human-final-decision flow
  are not part of this fix (later PR).

## L3 suspension on confirmed false pass (PR 28)

`controlled_active` also fails closed while an active false-pass suspension
exists for the pack (readiness check `active_false_pass_suspension`, severity
P0). L2 `production_assisted` is unaffected. See
[false-pass-incident-response.md](false-pass-incident-response.md).
