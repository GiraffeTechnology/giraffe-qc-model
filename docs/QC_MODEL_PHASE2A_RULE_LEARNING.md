# Phase 2A — LLM/VLM QC Rule Learning Engine (Skeleton)

Phase 2A adds the first real rule-learning loop on top of the Phase 1 visual QC
foundation. It lives under `src/qc_model/learning/`.

## 1. This is rule learning, not fine-tuning

"Learning" in Phase 2A means **proposing structured QC rules** from operator
requirements + Training Pack context:

- structured detection points
- proposed checkpoint category + AI role
- normal / defect visual features
- pseudo-defects / boundary cases
- decision rules
- review-required conditions

It does **NOT** mean fine-tuning model weights, LoRA training, full production
dataset training, automatic accuracy certification, automatic production
activation, or tablet-side rule generation. This distinction is enforced in
code comments, docs, and tests.

The loop:

```
operator QC requirement + Training Pack context
  -> LLM/VLM rule proposal
  -> structured learned detection points / visual rules / pseudo-defects
  -> supervisor review and confirmation
  -> approved rules become Training Pack assets
```

The model may propose, but it must not authorize itself.

## 2. Learning default runtime is `server`

Rule learning defaults to the **server** profile `qwen3.5-vl-8b-int4`.

- `tablet_mnn` (`qwen3.5-vl-2b-mnn`) is the edge profile that **executes
  confirmed rules**. It is **not** used for learning. An explicit attempt to
  learn on `tablet_mnn` is rejected and the job goes to a
  supervisor-review-required (`failed`) state — never a silent tablet learn.
- Any unknown / deprecated runtime name is rejected outright (it never silently
  falls back to server).

See `src/qc_model/learning/runtime_policy.py`.

## 3. Tablet MNN executes confirmed rules, not learning

The edge tablet runs confirmed detection points. Learning is a server-side /
schema-side workflow. Phase 2A does not touch the physical Android Pad MNN
runtime.

## 4. Supervisor confirmation is mandatory

Every learned proposal is created with `requires_supervisor_confirmation = true`
and starts in `proposed` status. Only supervisor-**approved** proposals can be
**applied** to a Training Pack. Applying:

- creates/updates detection points on the SKU catalog (`qc_detection_points`)
  plus a confirmed checkpoint classification (`qc_checkpoint_classifications`);
- preserves traceability (proposal keeps `applied_detection_point_id`,
  `approved_by`, `approved_at`; an `apply` approval row is recorded; the
  original operator requirement is preserved);
- never auto-activates a Training Pack or inspector;
- is idempotent.

Unapproved / rejected / proposed-only rules can never be applied.

## 5. Physical-measurement boundary during learning

If a requirement is a physical measurement (chain link count, length, weight,
diameter, spacing, angle, hardness, tensile force, chemical composition, lab
test), the engine proposes:

- `proposed_checkpoint_category = physical_measurement`
- `proposed_ai_role = record_only`
- a decision rule stating the operator measures with a fixture/ruler/gauge
- review-required conditions for missing measurement / fixture evidence

The validator additionally normalizes any over-permissive AI role down to the
safe default, so a physical measurement can never become AI-primary.

## 6. Provider-compatible, fail-closed architecture

Product learning services depend only on the
`QCRuleLearningProvider` abstraction and the registry — never on a Qwen-specific
class (statically asserted by
`tests/test_qc_rule_learning_provider_abstraction.py`). Providers:

- `MockRuleLearningProvider` — deterministic, for tests / dev UI;
- `Qwen35VLRuleLearningProvider` — default server adapter, **fails closed**
  (`valid=False`) in Phase 2A because no real backend is wired;
- `MainstreamRuleLearningAdapter` — mainstream LLM/VLM stub.

Provider failure, invalid output, or a forbidden runtime all drive the job to
`failed` + supervisor review. They never create active or applied rules.

The deterministic mock is used by the API/UI only when explicitly allowed
(`QC_LEARNING_ALLOW_MOCK=true` or `APP_ENV=test`); otherwise learning fails
closed.

## 7. Learning job state machine

```
draft -> input_ready -> running -> proposed -> reviewing
      -> approved | partially_approved | rejected -> applied
      -> failed | cancelled
```

## 8. API + UI

API (tenant-scoped) under the existing FastAPI app:

```
POST /api/qc/training-packs/{training_pack_id}/learning-jobs
GET  /api/qc/learning-jobs/{learning_job_id}
GET  /api/qc/training-packs/{training_pack_id}/learning-jobs
POST /api/qc/learning-jobs/{learning_job_id}/operator-requirements
POST /api/qc/learning-jobs/{learning_job_id}/sample-refs
POST /api/qc/learning-jobs/{learning_job_id}/run
GET  /api/qc/learning-jobs/{learning_job_id}/report
POST /api/qc/learning-jobs/{learning_job_id}/approve-proposals
POST /api/qc/learning-jobs/{learning_job_id}/reject-proposals
POST /api/qc/learning-jobs/{learning_job_id}/apply-approved-rules
```

UI: the existing Jinja2 admin UI is extended with `/admin/qc-model/learning`
(linked from `/admin/qc-model`). It makes the boundary visible: proposed rules
are not active until supervisor-approved and applied.

Persistence: `src/db/qc_learning_models.py` + migration `008`
(`qc_learning_jobs`, `qc_learning_inputs`,
`qc_learned_detection_point_proposals`, `qc_learned_visual_rule_proposals`,
`qc_learning_approvals`, `qc_learning_reports`).

## 9. Mocked tests do not prove visual accuracy

Phase 2A mocked-provider tests validate the learning **workflow and safety
gates** (structuring, physical boundary, approval gate, apply rules, runtime
policy, report audit, UI/API). They do **not** validate real qwen3.5-vl visual
accuracy, defect recall, or production readiness.

## 10. Future

Phase 2B will handle deeper VLM sample learning (reference/defect/boundary image
reasoning) with labeled real-world sample sets.
