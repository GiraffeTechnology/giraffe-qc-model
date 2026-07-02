# Real VLM Provider Integration (PR 26)

Replaces the mock-only production path with a **real, production-configurable**
server-side VLM provider for inspection. The provider fails closed and returns
schema-valid evidence; it never falls back to mock.

> Default server profile: `qwen3.5-vl-8b-int4`. Production learning/inspection
> never runs on `tablet_mnn` (the tablet edge profile consumes confirmed rules
> only). Mocked tests prove the workflow, not real visual accuracy.

## Provider

`ServerVLMInspectionProvider` (`src/qc_model/production/provider.py`):

- Configured via environment:
  - `QC_PRODUCTION_INSPECTION_PROVIDER=server_vlm` (selects the real path)
  - `QC_SERVER_VLM_BASE_URL` (required; empty ⇒ not configured)
  - `QC_SERVER_VLM_MODEL` (default = server runtime profile, `qwen3.5-vl-8b-int4`)
  - `QC_SERVER_VLM_API_KEY`, `QC_SERVER_VLM_TIMEOUT_SECONDS` (optional)
- **Fails closed** when not configured → `production_provider_not_configured`
  (API `503`). It does **not** fall back to mock.
- **Mock is L0-only** and is refused in `APP_ENV=production`.
- Sends a detection-point-specific inspection package (confirmed content +
  image references + capture metadata + prompt/schema version) to
  `POST {base_url}/v1/inspect`.

## Strict output schema (fail closed)

`parse_provider_response` requires a JSON object with all of:

```json
{
  "detection_point_code": "string",
  "disposition": "pass_recommended | reject_recommended | review_required | capture_retry_required | measurement_required",
  "observed_features": [], "defect_features": [], "normal_features_matched": [],
  "evidence_regions": [], "confidence": 0.0, "uncertainty": "string",
  "review_required_conditions": [], "provider": "string", "model": "string"
}
```

Non-object output, missing fields, wrong types, non-numeric confidence, or an
unknown disposition → the run is marked **failed** (no detection results
persisted). Missing required evidence still downgrades a recommended pass to
`review_required` (PR 25 rule).

## Audit: raw provider response

Every `ProductionDetectionResult` stores the verbatim provider JSON in
`raw_provider_response_json` (migration `014`, append-only), alongside provider,
model, and prompt/schema version, so a production decision can be audited back to
the exact model output.

## Runtime profiles

- `src/qc_model/production/runtime.py`:
  - `assert_server_side_runtime()` raises `TabletRuntimeNotAllowedForProduction`
    when `QC_VISION_RUNTIME_ENV=tablet_mnn` — production runs are server-side.
  - `production_vlm_profile()` returns the server profile.
- Sample learning's server adapter (`Qwen35VLSampleLearningProvider`) now takes
  its model from the **server** runtime profile.

## Migration

`alembic/versions/014_qc_production_raw_response.py` adds
`raw_provider_response_json` to `qc_production_detection_results`. Verified
`up → down → up` clean.

## Not done (later PRs)

- Live VLM backend deployment/wiring is environment configuration; CI uses a
  configured-provider stub (behaves like a real backend without a live server).
- Qualification / shadow mode / L3 (PR 27); false-pass incident loop (PR 28).
