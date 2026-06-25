# QC Standard Intake & Inspection Execution API

Two complementary API surfaces power the multi-SKU QC pipeline:

1. **Standard Intake API** — operators describe what to inspect; the system extracts checkpoints and creates a versioned standard revision.
2. **Inspection Execution API** — AI models (or operators) submit results against an active standard; the system applies the no-guess verdict policy and produces a final report.

---

## Standard Intake API

**Base path:** `/api/v1/qc/intakes`

### Intake lifecycle

```
POST /intakes               → received
POST /intakes/{id}/extract  → pending_confirmation
POST /intakes/{id}/confirm  → confirmed  (creates active QCSkuStandardRevision)
POST /intakes/{id}/reject   → rejected
```

### POST /api/v1/qc/intakes

Create a new standard intake session.

**Request body**

| Field              | Type   | Required | Default |
|--------------------|--------|----------|---------|
| `tenant_id`        | string |          | `"default"` |
| `sku_id`           | string | ✓        |         |
| `raw_text`         | string | ✓        |         |
| `source_type`      | string |          | `"api"` |
| `source_channel`   | string |          |         |
| `source_message_id`| string |          |         |
| `operator_id`      | string |          |         |

**Response 201**

```json
{
  "id": "...",
  "tenant_id": "default",
  "sku_id": "...",
  "source_type": "api",
  "status": "received",
  "raw_text": "Pearl count 3, petal integrity check.",
  "extracted_json": null,
  "confirmation_payload_json": null,
  "confidence_score": null,
  "parser_version": null
}
```

### GET /api/v1/qc/intakes/{intake_id}

Retrieve an existing intake session.

### POST /api/v1/qc/intakes/{intake_id}/media

Attach media (image, voice, PDF, etc.) to an intake session. Status 201 on success.

**Request body**

| Field           | Type   | Default             |
|-----------------|--------|---------------------|
| `media_type`    | string | `"image"`           |
| `media_role`    | string | `"standard_photo"`  |
| `image_url`     | string |                     |
| `local_path`    | string |                     |
| `sha256`        | string |                     |
| `mime_type`     | string |                     |
| `width_px`      | int    |                     |
| `height_px`     | int    |                     |
| `duration_ms`   | int    |                     |
| `metadata_json` | object |                     |

### POST /api/v1/qc/intakes/{intake_id}/extract

Parse `raw_text` into a structured checkpoint draft. No LLM required — uses deterministic regex and keyword matching (`deterministic-v1` parser).

Sets status to `pending_confirmation`. Populates `extracted_json` and `confirmation_payload_json`.

**Extraction logic**

The parser recognises:
- Counting checkpoints: `pearl[s] count <N>`, `rhinestone[s] count <N>`, `button[s] count <N>`, `hole[s] count <N>`, `barcode[s] count <N>`
- Structural checkpoints (keyword match): stamen centering, petal integrity, collar stitching, fabric stain, label position, surface scratch, edge burr, deformation check, barcode present, barcode readable, carton damage, seal integrity

Open questions are raised for counting checkpoints whose expected value could not be extracted.

### POST /api/v1/qc/intakes/{intake_id}/confirm

Confirm the extracted draft, creating an active `QCSkuStandardRevision`. Any previously active revision is archived.

**Request body**

| Field                | Type   | Required |
|----------------------|--------|----------|
| `confirmed_by`       | string | ✓        |
| `checkpoints`        | array  | ✓        |
| `operator_comment`   | string |          |

Each checkpoint in `checkpoints`:

| Field           | Type   | Required |
|-----------------|--------|----------|
| `point_code`    | string | ✓        |
| `label`         | string | ✓        |
| `description`   | string |          |
| `method_hint`   | string |          |
| `severity`      | string | default `"major"` |
| `expected_value`| string |          |
| `pass_criteria` | string |          |

**Response 200**

```json
{
  "revision_id": "...",
  "revision_no": 2,
  "status": "active",
  "sku_id": "...",
  "confirmed_by": "alice",
  "confirmation_id": "...",
  "checkpoint_count": 4
}
```

### POST /api/v1/qc/intakes/{intake_id}/reject

Reject the intake without creating a standard revision.

**Request body**

| Field         | Type   | Required |
|---------------|--------|----------|
| `rejected_by` | string | ✓        |
| `reason`      | string |          |

---

## Inspection Execution API

**Base path:** `/api/v1/qc/inspection-jobs`

### Job lifecycle

```
POST /inspection-jobs                  → pending
POST /inspection-jobs/{id}/media       → (attach photo)
POST /inspection-jobs/{id}/model-results → (ingest AI output)
POST /inspection-jobs/{id}/checkpoint-results → (manual result)
POST /inspection-jobs/{id}/incidental-findings → (flag finding)
POST /inspection-jobs/{id}/finalize    → pass | fail | review_required
GET  /inspection-jobs/{id}/report      → final report
```

### POST /api/v1/qc/inspection-jobs

Create a new inspection job. Snapshots the SKU's active standard revision at creation time — subsequent standard updates do not affect existing jobs.

**Request body**

| Field        | Type   | Required | Default     |
|--------------|--------|----------|-------------|
| `tenant_id`  | string |          | `"default"` |
| `sku_id`     | string | ✓        |             |
| `job_ref`    | string |          |             |
| `created_by` | string |          |             |
| `notes`      | string |          |             |

**Response 201**

```json
{
  "id": "...",
  "tenant_id": "default",
  "sku_id": "...",
  "active_standard_revision_id": "...",
  "job_ref": "JOB-2024-001",
  "status": "pending",
  "created_by": "alice"
}
```

### GET /api/v1/qc/inspection-jobs/{job_id}

Retrieve an existing inspection job.

### POST /api/v1/qc/inspection-jobs/{job_id}/media

Attach an inspection image or video. Status 201 on success.

| Field       | Type   |
|-------------|--------|
| `image_url` | string |
| `local_path`| string |
| `angle`     | string |
| `view_type` | string |
| `sha256`    | string |
| `width_px`  | int    |
| `height_px` | int    |
| `mime_type` | string |

### POST /api/v1/qc/inspection-jobs/{job_id}/model-results

Ingest structured AI model output. Validates every `point_code` against the job's snapshotted revision before persisting anything (atomic rejection on unknown codes).

**Request body**

| Field              | Type   | Required |
|--------------------|--------|----------|
| `provider`         | string | ✓        |
| `model_name`       | string | ✓        |
| `raw_output`       | object | ✓        |
| `media_id`         | string |          |
| `http_status`      | int    |          |
| `elapsed_ms`       | int    |          |

`raw_output` schema:

```json
{
  "checkpoint_results": [
    {
      "point_code": "PEARL_COUNT",
      "result": "pass",
      "observed_value": "3",
      "confidence": 0.99,
      "notes": null
    }
  ],
  "incidental_findings": [
    {
      "severity": "minor",
      "description": "Slight dust on petal edge.",
      "location_hint": "top-right"
    }
  ]
}
```

Valid `result` values: `pass`, `fail`, `not_visible`, `low_confidence`, `unsupported`

Returns **400** if any `point_code` is not in the job's snapshotted revision.

### POST /api/v1/qc/inspection-jobs/{job_id}/checkpoint-results

Submit a single checkpoint result (manual or corrective). Validates detection point ownership (tenant, SKU, revision, is_active). Rejects duplicates for the same `(job_id, detection_point_id)` pair.

### POST /api/v1/qc/inspection-jobs/{job_id}/incidental-findings

Record an incidental finding not tied to a specific checkpoint.

| Field           | Type   | Default   |
|-----------------|--------|-----------|
| `description`   | string | ✓         |
| `severity`      | string | `"minor"` |
| `location_hint` | string |           |
| `evidence_json` | object |           |

### POST /api/v1/qc/inspection-jobs/{job_id}/finalize

Apply the no-guess verdict policy and write the final report. Idempotent — returns the existing report if the job is already finalised.

**Verdict logic**

| Condition                                              | Verdict           |
|--------------------------------------------------------|-------------------|
| Any checkpoint result = `fail`                        | `fail`            |
| Any checkpoint missing/`not_visible`/`low_confidence`/`unsupported`, or major+ incidental finding | `review_required` |
| All checkpoints = `pass`, no serious findings          | `pass`            |

**Response 200**

```json
{
  "id": "...",
  "job_id": "...",
  "overall_result": "pass",
  "checkpoint_results_count": 4,
  "findings_count": 0,
  "summary_text": null
}
```

### GET /api/v1/qc/inspection-jobs/{job_id}/report

Retrieve the final report. Returns **404** if the job has not been finalised yet.

---

## Seed SKUs

Four fixture SKUs are available for testing and initial deployment:

| Item Number        | Category              | Checkpoints (4)                                                      |
|--------------------|-----------------------|----------------------------------------------------------------------|
| `FLOWER-BROOCH-001`| Jewelry               | STAMEN_CENTERING, PEARL_COUNT (×3), RHINESTONE_COUNT (×8), PETAL_INTEGRITY |
| `SHIRT-CUSTOM-001` | garment_textile       | BUTTON_COUNT (×7), COLLAR_STITCHING, FABRIC_STAIN, LABEL_POSITION   |
| `METAL-BRACKET-001`| industrial_component  | HOLE_COUNT (×4), SURFACE_SCRATCH, EDGE_BURR, DEFORMATION_CHECK      |
| `CARTON-LABEL-001` | packaging_label       | BARCODE_PRESENT, BARCODE_READABLE, CARTON_DAMAGE, SEAL_INTEGRITY     |

Seed via `seed_all_fixtures(db)` from `src.db.seed_data`.
