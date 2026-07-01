# QC Source Ingestion Workbench (PR 21)

Ingest QC source materials (drawings, specs, standards, samples, natural-
language / speech operator input) and run a **deterministic / mocked**
extraction step that produces **draft fragments only**.

> **Draft-only guarantee.** Nothing produced by this feature can become an
> active rule. There is no `active` status at this layer — every entity is
> `draft` / `reviewed` / `rejected`. No code path here writes to a Training
> Pack table. Activation only happens later via the Training Pack apply path
> (a different PR).

## Entity model

| Entity | Purpose |
|---|---|
| `QCSourceDocument` | A registered piece of source material (text, file ref, or image ref), tenant-scoped, linked to a Training Pack. |
| `SourceExtractionJob` | Tracks one extraction run (status, provider, timestamps, error). |
| `QCSourceFragment` | An extracted candidate unit derived from a source document. |
| `QCRequirementDraft` | A draft requirement derived from a fragment — not an active rule. |
| `QCBoundaryDraft` | A draft physical/rule boundary derived from a fragment — not an active rule. |

All entities are tenant-scoped (`tenant_id` column, filtered on every query) and
**append-safe**: a new extraction run creates a *new* job plus *new*
fragments/drafts; it never mutates prior output. Tables are added by Alembic
migration `009` (`src/db/qc_source_models.py`).

### `QCSourceType`

`natural_language`, `process_spec`, `inspection_standard`, `drawing`,
`cad_export`, `pdf`, `image`, `standard_photo`, `positive_sample`,
`defect_sample`, `boundary_sample`, `capture_artifact_sample`,
`speech_to_text`. Unrecognized types are rejected at the API boundary with a
**422**.

### Fragment types

Each fragment is classified as one of:
`possible_detection_point`, `possible_physical_measurement`,
`possible_boundary_condition`, `missing_tolerance_or_count`,
`possible_pseudo_defect`, `unclear_requirement`, `requires_supervisor_review`.

Fragments carry a UI grouping hint `candidate_label`
(`detection_point` | `boundary_rule` | `review`).

## Extraction pipeline (PR 21 scope)

The extractor (`src/qc_model/ingestion/extractor.py`) is **deterministic and
mocked** — no live LLM/VLM call. It uses simple heuristics (regex for numeric
tolerance patterns; keyword matching for `must` / `shall` / `±` / `count` /
`align` / pseudo-defect and boundary vocabularies) to exercise the full
pipeline shape and emit realistic fragment shapes.

- Textual sources (`natural_language`, `process_spec`, `inspection_standard`,
  `speech_to_text`) are parsed statement-by-statement.
- Binary/image/CAD/PDF references yield a single `requires_supervisor_review`
  fragment noting a real VLM pass is needed.

**This is a placeholder for the real LLM/VLM extraction that lands in PR 22/23.**
The fragment shapes are stable so PR 22 can swap in a real extractor without a
schema change. Mocked extraction proves the pipeline shape, not accuracy.

## API (tenant-scoped)

```
POST   /api/qc/training-packs/{training_pack_id}/sources     # 422 on bad source_type; 404 cross-tenant pack
GET    /api/qc/training-packs/{training_pack_id}/sources
GET    /api/qc/sources/{source_id}
POST   /api/qc/sources/{source_id}/extract                   # creates a job + fragments; never touches Training Pack
GET    /api/qc/source-extraction-jobs/{job_id}
GET    /api/qc/source-extraction-jobs/{job_id}/fragments
```

Tenant isolation is enforced on every endpoint, including nested lookups:
fetching a job's fragments verifies the job belongs to the requesting tenant
first. A `training_pack_id` already owned by another tenant (seen on that
tenant's learning jobs or sources) is rejected with a 404.

## UI

`/admin/qc-model/training-packs/{training_pack_id}/sources` (linked from each
learning job on `/admin/qc-model/learning`). Extends the existing FastAPI +
Jinja2 admin UI — no new frontend framework. It supports entering
natural-language requirements / process specs, registering drawing/PDF/image
references, selecting the source type, triggering extraction, and viewing
fragments grouped by type with detection-point vs boundary-rule badges (badges
only — approval UI comes in PR 22).

---

## PR 22 — LLM rule authoring from source fragments

PR 22 converts PR 21 `QCSourceFragment` rows into structured **learned rule
proposals** (`src/qc_model/authoring/`). Proposals are **draft only** and
**reuse PR 20's proposal table + approval workflow** (`ProposalStatus`,
`approved_by`/`approved_at`); this PR still does **not** touch Training Pack
activation (that arrives via PR 20's existing approval flow plus PR 24's
readiness gate).

### Proposal generation pipeline

`RuleAuthoringJob` tracks one authoring run over a fragment (or an extraction
job's fragments). The run calls a `QCRuleAuthoringProvider` (deterministic mock
in dev/test; the `qwen3.5-vl` adapter fails closed with no real backend), then
the **hard validator** guards and persists proposals into
`qc_learned_detection_point_proposals` (tagged with `rule_authoring_job_id` and
`source_fragment_id`).

Endpoints (tenant-scoped):

```
POST /api/qc/source-fragments/{fragment_id}/propose-rules
POST /api/qc/source-extraction-jobs/{job_id}/propose-rules
GET  /api/qc/rule-authoring-jobs/{job_id}
GET  /api/qc/rule-authoring-jobs/{job_id}/proposals
```

The PR 21 workbench page is extended to show, per fragment, the proposed
detection point(s), checkpoint category, AI role, decision rule,
`questions_or_ambiguities`, and Approve / Edit / Reject controls.

### Physical-measurement guard (hard invariant)

Enforced in `src/qc_model/authoring/validator.py`, independent of the LLM: if
`checkpoint_category == physical_measurement`, `ai_role` is **forced** to
`record_only` and the override is recorded in a supervisor-visible note. A
supervisor edit that changes the category re-runs the same guard. This is
covered by an adversarial test that feeds a hostile LLM response and asserts the
override still holds.

### Never guess missing values

The system never fabricates a missing count, tolerance, required view,
orientation, color range, measurement method, or pass/fail threshold. When any
is missing/ambiguous it adds a `questions_or_ambiguities` entry instead. Tests
assert a fragment missing a tolerance (or count) produces a question and no
fabricated value.

### Fail-closed

Provider failure or malformed/partial LLM output → `RuleAuthoringJob.status =
failed`, **zero** proposals persisted (never best-effort parsed into an
approvable proposal), with the error surfaced via `GET
/api/qc/rule-authoring-jobs/{job_id}`.

---

## PR 23 — VLM sample learning

PR 23 learns structured **visual rule memory** from grouped sample images
(`src/qc_model/sample_learning/`). It reuses the established provider pattern
(deterministic mock in dev/test; the `qwen3.5-vl` adapter fails closed with no
real backend) and PR 20's approve/reject shape.

### Five sample types

`reference`, `positive`, `defect`, `boundary`, `capture_artifact`
(`SampleGroup.sample_type`). Invalid types are rejected 422; a detection point
from another tenant is rejected 404.

### Pipeline + per-sample provenance

`SampleLearningJob` runs a VLM over a `SampleGroup`. It produces one
`VisualFeatureObservation` per sample image (never collapsed to an aggregate),
each preserving `source_sample_id`, `image_reference`, `detection_point_code`,
`feature_type`, `evidence_region`/bbox (nullable), `confidence`, `uncertainty`,
`rule_implication`, and `requires_human_review`, plus the structured lists
(normal/acceptable/defect features, known pseudo-defects, capture-artifact
risks, evidence-required, review-required conditions). Each observation also
gets an append-only `SampleEvidenceAnchor` linking it to the exact sample image
+ region. Observations aggregate into a `VisualRuleMemory` (plus
`PseudoDefectRule` / `CaptureArtifactRule` rows).

### Two-step approve → apply

Approval and application are **distinct**:

```
POST /api/qc/training-packs/{training_pack_id}/sample-learning-jobs
GET  /api/qc/sample-learning-jobs/{job_id}
GET  /api/qc/sample-learning-jobs/{job_id}/observations
GET  /api/qc/sample-learning-jobs/{job_id}/visual-rule-memory
POST /api/qc/visual-rule-memory/{memory_id}/approval          # approve | edit | reject
POST /api/qc/training-packs/{training_pack_id}/apply-approved-visual-rule-memory
```

`apply-approved-visual-rule-memory` is the **only** path that writes learned
visual rules into a Training Pack (`qc_confirmed_visual_rules`). It is gated
server-side: applying non-`approved` memory returns **409**.

### No-silent-overwrite guarantee

If a confirmed visual rule already exists for the same training pack + detection
point + feature type with **different** content, the apply call fails (**409**)
and requires explicit supervisor resolution — it never overwrites. Identical /
same-source re-apply is idempotent.

### Fail-closed

VLM failure or malformed/invalid output → `SampleLearningJob.status = failed`
with no observations or memory persisted as approvable.

UI: `/admin/qc-model/training-packs/{training_pack_id}/sample-learning` — register
sample groups, run learning, view per-sample observations, pseudo-defect and
capture-artifact lists, and Approve / Reject then Apply visual rule memory.

---

## PR 24 — Training Pack readiness & completeness gate

PR 24 (`src/qc_model/readiness/`) makes `exam_ready` / `active` depend on
**confirmed QC knowledge completeness**, not just structural checks.

> **Behavioral change.** Transitions into `exam_ready` and `active` now call the
> readiness evaluator first. Any Training Pack currently in `exam_ready` /
> `active` may no longer satisfy the gate under the new checks. Whether to
> backfill / re-evaluate existing packs is **flagged for supervisor decision**
> (this PR does not silently migrate existing pack statuses).

### The 10 checks (`evaluate_readiness`)

1. **Source documents reviewed** — every `QCSourceDocument` is reviewed/handled (not draft).
2. **Detection points confirmed** — no proposal left `proposed`.
3. **Physical-measurement boundaries confirmed** — physical proposals approved/applied with a decision rule.
4. **Rule-verification requirements confirmed** — approved or rejected.
5. **Visual rules reviewed** — no `VisualRuleMemory` left `proposed`.
6. **No unresolved questions/ambiguities** — open questions on resolved proposals — **waivable** (see below).
7. **Sample coverage sufficient** — provisional default: ≥1 reviewed positive group and ≥1 reviewed defect/boundary group.
8. **No unreviewed conflicts** — no approved memory that conflicts with an existing confirmed rule (PR 23's no-silent-overwrite).
9. **No pending high-risk pseudo-defects** — high-risk `PseudoDefectRule` entries resolved.
10. **No pending critical defect rules** — critical-severity defect proposals resolved.

### Status behavior

- Any of checks **1–6, 8–10** incomplete ⇒ **must not** enter `exam_ready`.
- Check **7** insufficient ⇒ **may** enter `on_trial`, **must not** enter `active`.

`gate_transition(db, training_pack_id, target_status)` extends status-transition
logic to consult the evaluator for `exam_ready` / `active` / `on_trial` targets.

### Waiver mechanism (ambiguities only)

Only check 6 is waivable. A waiver requires an authenticated supervisor
identity **and** a justification, is scoped to a **specific** item (no pack-level
blanket waivers), and is appended to an audit log (`qc_readiness_waivers`, never
mutated). Checks 1–5 and 8–10 are **non-waivable** and cannot be bypassed even
if a waiver is submitted against them (rejected at the service layer).

### API + UI

```
GET  /api/qc/training-packs/{training_pack_id}/readiness                 # per-check detail
POST /api/qc/training-packs/{training_pack_id}/status-transition         # gated transition check
POST /api/qc/training-packs/{training_pack_id}/readiness-waivers         # supervisor + justification + item
GET  /api/qc/training-packs/{training_pack_id}/readiness-waivers
```

UI: `/admin/qc-model/training-packs/{training_pack_id}/readiness` — the readiness
checklist (pass/fail + blocking items), `on_trial` vs `active` distinction, a
per-item waive action for the ambiguity check only, and the waiver audit log.
