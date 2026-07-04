# CV Result Schema

A CV result is **evidence for a human/QC decision — not a QC verdict.**

## Upload

`POST /api/edge-cv/jobs/:id/result` (Bearer device token):

```json
{
  "device_id": "edge_dev_…",
  "session_id": "edge_sess_…",
  "model_id": "cv_model_…",
  "result_type": "detection",
  "confidence": 0.82,
  "pass_fail_hint": "needs_human_review",
  "detections": [
    { "label": "pearl_candidate", "bbox": [120, 88, 22, 22], "confidence": 0.91 },
    { "label": "petal_damage_candidate", "bbox": [330, 210, 56, 41], "confidence": 0.74 }
  ],
  "measurements": { "pearl_candidate_count": 8, "flower_core_offset_ratio": 0.08 },
  "features": {},
  "evidence_assets": [
    { "asset_type": "annotated_image", "asset_uri": "storage://cv-output/job/annotated.jpg", "asset_hash": "sha256:…" }
  ],
  "raw_output": { "runner": "mock_edge_cv", "runtime_ms": 318 },
  "model_hash": "mock-hash"
}
```

## Fields

| Field | Meaning |
|---|---|
| `detections_json` | List of candidate detections: `label`, `bbox` `[x,y,w,h]`, `confidence`. |
| `measurements_json` | Scalar measurements/counts (pearl count, offset ratio, …). |
| `features_json` | Optional lightweight feature vectors / descriptors. |
| `raw_output_json` | Runner-specific raw output (runtime, runner name, debug). |
| `result_hash` | SHA-256 over the canonical result payload (dedup/audit). |

### Evidence assets (`cv_result_assets`)

`asset_type` ∈ `input_thumbnail`, `annotated_image`, `crop`, `mask`, `heatmap`,
`debug_image`. `asset_uri` is required; `asset_hash`, `width`, `height`,
`metadata` are optional. An unknown `asset_type` is rejected.

### `pass_fail_hint` — a hint only

Allowed: `pass`, `fail`, `unknown`, `needs_human_review`.

> **`pass_fail_hint` is only a hint. It is NOT the final QC decision.** The QC
> layer re-validates every operator-confirmed test point; the Jetson/CPU result
> is supporting evidence (candidate bboxes, counts, annotated images), never the
> judgement. CPU-fallback and mock results always report `needs_human_review`.

## Validation (before persistence)

The service rejects a result for any of:

- unknown `job_id`; wrong `device_id`; wrong/stale `session_id`; expired lease
  → **`409`**, and job state is **not** mutated (a stale session can never
  corrupt current state);
- invalid status transition; missing/invalid `result_type`; invalid
  `pass_fail_hint`; unknown asset type; missing asset URI; model-hash mismatch
  → **`422`**, and the job is escalated to `manual_review_required`.

## Idempotency

One result per `(cv_job_id, device_id, session_id)` (DB unique constraint). A
duplicate upload from the same device+session returns the **existing** result —
no second row, no double completion.
