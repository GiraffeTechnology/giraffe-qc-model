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
