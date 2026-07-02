# Production Deployment Hardening (PR 29)

Operational hardening for running `giraffe-qc-model` in a real production
environment. This PR adds environment/provider gating guarantees, observability,
audit immutability, and the deployment documentation pass.

> **Mocked tests prove workflow only, not production visual accuracy.**
> **Production Assisted Mode (L2) requires a human final decision.**
> **Controlled Active Mode (L3) requires qualification and false-pass
> monitoring.**

## Environment &amp; provider controls

- `APP_ENV=production` **disables all mock/fake/test providers, and no override
  env var can re-enable them**:
  - `get_production_inspection_provider()` refuses the mock inspection provider
    (`production_provider_not_configured`).
  - `sample_learning_mock_allowed()` and `fake_provider_allowed()` return `False`
    even when `QC_SAMPLE_LEARNING_ALLOW_MOCK=true` / `QC_ALLOW_TEST_ADAPTER=true`
    — production wins over every override flag.
- Production APIs **fail closed** when the real provider is unavailable: a
  selected `server_vlm` provider with no `QC_SERVER_VLM_BASE_URL` raises
  `production_provider_not_configured` on use — it never falls back to mock.
- Provider eligibility is exposed for readiness/ops:

  ```
  GET /api/qc/production/provider-eligibility
  → { selected, provider_name, model, configured, production_eligible,
      app_env, mock_allowed }
  ```

## Observability

`src/qc_model/observability.py` emits structured log records and increments
in-process metrics (scrape via `GET /api/qc/production/metrics`) for:

`readiness_gate_result`, `production_inspection_run`, `provider_latency`,
`provider_error`, `schema_validation_error`, `review_required`,
`false_pass_incident`, `false_fail_incident`, `human_override`,
`qualification_result`.

Semantics hardened per review:

- **Schema vs. provider errors.** A provider *response contract* failure —
  non-object, missing/typed fields, invalid disposition, non-numeric confidence,
  non-list evidence regions, malformed JSON, any `parse_provider_response`
  failure — is counted as `schema_validation_error`. Only unavailability /
  timeout / transport / HTTP failures (and unconfigured providers) count as
  `provider_error` / `production_provider_not_configured`.
- **Bounded latency.** `provider_latency` is stored as a bounded O(1) running
  aggregate (`count`, `sum_ms`, `min_ms`, `max_ms`) — memory does not grow with
  the number of requests. `snapshot()` exposes `count`, `avg_ms`, `min_ms`,
  `max_ms`.
- **Human override.** `human_override` is emitted only when the human decision
  *family* differs from the model recommendation *family* over
  `{pass, reject, review}`. A model review-family recommendation
  (`review_required` / `capture_retry_required` / `measurement_required`)
  followed by a human `review` decision is a **match, not an override**; clearing
  a review to pass, or contradicting a `pass_recommended` / `reject_recommended`,
  is an override.

`observability.record(...)` never raises — observability cannot break a
production path.

## Database &amp; migrations

- Migrations `009 → 016` apply `upgrade head → downgrade base → upgrade head`
  cleanly (verified by `test_migration_up_down_up` and CI acceptance).
- No migration drops production audit data.
- **Append-only audit tables are not mutable through public APIs**:
  `qc_readiness_waivers`, `qc_production_evidence_packets`,
  `qc_production_final_decisions`, `qc_qualification_approvals`,
  `qc_incident_audit_events`, and the incident/suspension records expose only
  create/read routes (no `PUT`/`PATCH`/`DELETE`); enforced by
  `test_audit_resources_have_no_mutating_api`.

## Security / audit

- A supervisor/operator identity is required for: readiness waiver, production
  final decision, qualification approval, controlled-active enablement (via the
  qualification approval + suspension lift), and incident confirmation / lift.
- Audit writes include `tenant_id`, actor id, timestamp, and a reason/comment.

## Runtime profiles

- Server profile (`qwen3.5-vl-8b-int4`) is used for production learning and
  inspection. The `tablet_mnn` edge profile consumes confirmed rules only and is
  blocked from production runs / rule generation. The obsolete desktop-PC edge
  profile name is not used anywhere in `src`/`docs` (enforced by a terminology
  test).

## Deployment checklist

```
APP_ENV=production
QC_PRODUCTION_INSPECTION_PROVIDER=server_vlm
QC_SERVER_VLM_BASE_URL=<real server VLM endpoint>
QC_SERVER_VLM_MODEL=qwen3.5-vl-8b-int4   # optional; defaults to server profile
AIVAN_/QC_ tenant scoping configured per tenant
```

Verify `GET /api/qc/production/provider-eligibility` returns
`production_eligible: true` before enabling any production inspection.
