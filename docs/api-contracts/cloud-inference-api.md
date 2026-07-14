# Cloud Operator Inference API — Architecture v2 Contract

**Contract version:** `2.0`

**Owner:** WS4 (`claude/ws4-operator-jetson-integration`)

**Consumers:** Android Operator pipeline, WS3 health screen through
`pad-health-state.md`, Server S4 submission path, and WS8 CV pre-analysis

**Implementation status:** `[CLIENT IMPLEMENTED IN WS4]`. The Android Operator
client implements signed batched crop upload, health/probe reads, fail-closed
queueing, and S4 forwarding. Deployment of a real cloud serving stack and
real-cellular SLO evidence remain environment/manual prerequisites.

This is the only VLM inference API in the production Operator path. The Pad and
Jetson Nano detect QC points, create bounded crops, and send all crops for one
job in one request to the configured cloud VLM provider. The Architecture v2
deployment default is `qwen3-vl-30b-A3B`; it is a replaceable provider default,
not the product identity or an ecosystem lock-in. The Nano runs no VLM.

## 1. Binding rules

- A request contains **QC-point crops only**. A full capture or reference frame
  must be rejected with `422 full_frame_not_allowed`.
- Every crop is JPEG (`image/jpeg`), no larger than the effective configured
  `max_crop_bytes` (default and hard ceiling `204800` bytes). Resize and JPEG
  quality come from detection-point or site configuration, not client constants.
- A compression profile resolves at least `max_crop_bytes`,
  `max_longest_side_px`, and `jpeg_quality`. The normal longest-side range is
  640–768 px; the effective value travels in the signed Bundle/site
  configuration and is not compiled into the client.
- All crops for a job are uploaded in one `multipart/form-data` request. There
  is no production endpoint for serial per-crop inference.
- The client starts one request after all crops are prepared. The HTTP stack may
  stream multipart bytes, but must not create independent crop round-trips.
- No cloud response means no QC result. Timeout, loss of both links, or an
  unhealthy cloud queues the job as `pending_upload`; it never invokes a local
  VLM or manufactures a verdict.
- Cloud point results are sent unchanged through the Pad outbox to
  `POST /api/qc/results/submissions`, where S4 recomputes and stores the
  authoritative server verdict. The immediate Pad label is a cloud recognition
  result until that recomputation is returned.
- The end-to-end target is 10 seconds from capture confirmation to result
  rendering. This contract provides timestamps; only real-link measurements may
  be presented as SLO evidence.

All timestamps are RFC 3339 UTC with millisecond precision. IDs are opaque,
case-sensitive strings. Unknown response fields must be ignored; unknown enum
values must fail closed to an `unknown`/non-submittable UI state.

## 2. Authentication, signing, and replay protection

All endpoints require TLS 1.2+ and an Operator-device bearer token scoped to a
single tenant, Pad, and workstation. The service derives tenant identity from
the token; a caller-supplied `tenant_id` is not accepted.

The inference and probe requests also carry a detached Ed25519 device signature:

```http
Authorization: Bearer <short-lived-device-token>
Idempotency-Key: <job_id>
X-QC-Key-Id: <provisioned-pad-key-id>
X-QC-Timestamp: 2026-07-14T03:04:05.678Z
X-QC-Nonce: <128-bit-random-base64url>
X-QC-Content-SHA256: <lowercase-hex>
X-QC-Signature: <base64-ed25519-signature>
```

The Pad signing key is generated and held in Android Keystore. It is not the
Bundle signing key. The signature input is UTF-8:

```text
QC-CLOUD-INFERENCE-V1
<UPPERCASE_METHOD>
<PATH>
<X-QC-Timestamp>
<X-QC-Nonce>
<X-QC-Content-SHA256>
<job_id-or-empty>
```

Each displayed line is terminated by one LF byte, including the final line.

For multipart inference, `X-QC-Content-SHA256` is SHA-256 over canonical JSON
for the `manifest` part (UTF-8, sorted object keys, no insignificant
whitespace), followed by `\n`, followed by each declared crop SHA-256 and `\n`
in manifest order. The server separately hashes every received crop and rejects
a mismatch. For a binary probe it is SHA-256 of the body bytes.

The service rejects timestamps outside a 300-second window and re-use of the
same `(key_id, nonce)` for 10 minutes. A repeated `Idempotency-Key` with the
same authenticated content digest returns the original job/result; a different
digest returns `409 idempotency_conflict`.

## 3. Endpoints

| Method and path | Purpose |
|---|---|
| `POST /api/v2/operator-inference/jobs` | One synchronous, batched crop submission and recognition. |
| `GET /api/v2/operator-inference/jobs/{job_id}` | Reconcile a request after client timeout; never starts inference. |
| `GET /api/v2/operator-inference/health` | Authenticated reachability/readiness check used by Pad health state. |
| `POST /api/v2/operator-inference/network-probe` | Signed upload probe, maximum 64 KiB; does not invoke a model or create a QC job. |

### 3.1 Batched inference request

`POST /api/v2/operator-inference/jobs` uses `multipart/form-data`. It contains
one UTF-8 `application/json` part named `manifest` and one `image/jpeg` part for
each `crop_part` named in the manifest.

```json
{
  "schema_version": "2.0",
  "request_id": "018fa8c1-7cb1-7bf2-9f3a-123456789abc",
  "job_id": "job_01J2ABCDEF",
  "pad_device_id": "pad_hk_014",
  "workstation_id": "line3_station2",
  "standard_revision_id": "rev_01J2STANDARD",
  "bundle_version": "2026.07.14-3",
  "capture_confirmed_at": "2026-07-14T03:04:05.100Z",
  "client_deadline_at": "2026-07-14T03:04:14.100Z",
  "compression_profile_id": "site-hk-default-v3",
  "points": [
    {
      "point_code": "front_rhinestones",
      "crop_id": "crop_01J2A",
      "crop_part": "crop_01J2A.jpg",
      "crop_sha256": "<64-lowercase-hex>",
      "encoded_bytes": 187432,
      "width_px": 704,
      "height_px": 512,
      "region_in_capture": {"x": 0.12, "y": 0.20, "w": 0.32, "h": 0.28},
      "severity": "major",
      "expected_value": "24 rhinestones",
      "pass_criteria": "all expected rhinestones present and attached",
      "expected_features": {"rhinestone_count": 24},
      "cv_config": {
        "analyzers": ["rhinestone_count"],
        "parameters": {"min_radius_px": 3, "max_radius_px": 16}
      },
      "cv_status": "completed",
      "cv_analysis": {
        "schema_version": "1.0",
        "analyzers": [{"analyzer": "rhinestone_count", "backend": "contour", "count": 24, "centers": [], "boxes": [], "confidence": 0.84}],
        "deviations": [],
        "verdict_effect": "informational_only",
        "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points"
      }
    }
  ],
  "client_timing": {
    "capture_confirmed_at": "2026-07-14T03:04:05.100Z",
    "cv_started_at": "2026-07-14T03:04:05.140Z",
    "cv_completed_at": "2026-07-14T03:04:06.280Z",
    "upload_started_at": "2026-07-14T03:04:06.310Z",
    "per_crop": [
      {"crop_id": "crop_01J2A", "encode_started_at": "2026-07-14T03:04:05.900Z", "encode_completed_at": "2026-07-14T03:04:06.250Z"}
    ]
  }
}
```

`points` must be non-empty and `point_code` and `crop_id` must be unique in a
job. `region_in_capture` uses normalized coordinates in `[0,1]` and is metadata
only; it cannot be used to reconstruct or request the full frame. The service
must verify the declared media type, size, dimensions, and digest before model
execution.

When `cv_config` is absent, clients retain the pre-WS8 `not_configured`/`null`
wire values. When configured, the Nano runs the shared `cv_preanalysis` package
inside the two-second CV/crop budget and sends its canonical JSON. The cloud
adapter inserts the JSON verbatim between `<CV_PREANALYSIS_JSON>` and
`</CV_PREANALYSIS_JSON>`, followed by the supporting-evidence warning. A CV
failure sets `cv_status: failed`, logs the error, omits the prompt block, and
does not block VLM recognition. `deviations` are informational only.

### 3.2 Successful response

```json
{
  "schema_version": "2.0",
  "request_id": "018fa8c1-7cb1-7bf2-9f3a-123456789abc",
  "job_id": "job_01J2ABCDEF",
  "status": "completed",
  "recognition_overall_result": "review_required",
  "point_results": [
    {
      "point_code": "front_rhinestones",
      "crop_id": "crop_01J2A",
      "result": "uncertain",
      "confidence": 0.71,
      "evidence": "The crop does not show all expected positions clearly.",
      "evidence_regions": [{"x": 0.08, "y": 0.16, "w": 0.12, "h": 0.14}],
      "cv_status": "not_configured"
    }
  ],
  "model": {
    "provider_adapter": "configured-cloud-vlm",
    "family": "qwen3-vl-30b-A3B",
    "deployment_revision": "opaque-deployment-id"
  },
  "timing": {
    "request_received_at": "2026-07-14T03:04:07.010Z",
    "inference_started_at": "2026-07-14T03:04:07.120Z",
    "inference_completed_at": "2026-07-14T03:04:09.980Z",
    "response_sent_at": "2026-07-14T03:04:10.020Z",
    "queue_ms": 110,
    "inference_ms": 2860
  }
}
```

Per-point `result` is `pass | fail | uncertain`; overall recognition is
`pass | fail | review_required`. Missing or duplicate point results make the
whole response invalid and the client records no verdict. Confidence is in
`[0,1]`; it is evidence, never permission to turn `uncertain` into `pass`.

The Pad appends `upload_completed_at`, `response_received_at`, and
`verdict_rendered_at` locally. Its multipart progress listener also records
`upload_started_at` and `upload_completed_at` for each crop part as its bytes
cross the transport. These post-manifest facts are persisted with the job and
sent through the S4 outbox telemetry; they are not retroactively inserted into
the already-sent manifest. Clock skew between client and server is retained in
telemetry; durations are calculated from monotonic clocks on each host.

### 3.3 Status reconciliation

`GET /api/v2/operator-inference/jobs/{job_id}` returns the same completed
payload, or:

```json
{"schema_version":"2.0","job_id":"job_01J2ABCDEF","status":"processing","retry_after_ms":250}
```

`status` is `processing | completed | failed`. `404 job_not_found` means the
client may retry the original signed POST within its bounded retry policy.

The Pad persists the original manifest and bounded crop files before reporting
`pending_upload`. Its background reconciler probes the same `job_id`; a 404 is
resubmitted with the original idempotency key, while a completed response is
stored as a durable recovered-result record and removed from the pending queue.
It is not auto-submitted as a human verdict. Retryable/processing responses are
rescheduled after a delay.

### 3.4 Health and link probe

Health returns HTTP `200` even when not ready so transport reachability and
service readiness remain distinct:

```json
{
  "schema_version": "2.0",
  "service_status": "up",
  "accepting_jobs": true,
  "model_loaded": true,
  "deployment_revision": "opaque-deployment-id",
  "server_time": "2026-07-14T03:04:05.678Z"
}
```

`service_status` is `up | degraded`; `accepting_jobs=false` is non-submittable.
Health values are live observations, not cached assumptions.

The network probe accepts `application/octet-stream` up to 65536 bytes and
returns `bytes_received`, `request_received_at`, and `response_sent_at`. The Pad
combines probe results with moving averages from real transfers. Probe success
does not imply model readiness and is never recorded as inference latency.

## 4. Error and timeout semantics

Every non-2xx response uses:

```json
{
  "error": {
    "code": "cloud_not_ready",
    "message": "Inference service is not accepting jobs.",
    "retryable": true,
    "retry_after_ms": 500,
    "job_state": "not_created"
  }
}
```

| HTTP | Code | Client behavior |
|---:|---|---|
| 400 | `malformed_manifest` | Permanent failure; do not retry unchanged. |
| 401 | `authentication_required` / `bad_signature` / `replay_detected` | Block and require credential repair. |
| 403 | `device_not_authorized` | Block; never switch to a mock/local verdict. |
| 409 | `idempotency_conflict` | Block and surface integrity error. |
| 413 | `crop_too_large` / `request_too_large` | Re-encode from configured profile, then bounded retry. |
| 422 | `full_frame_not_allowed` / `invalid_crop` / `unsupported_schema` | Permanent failure for that payload. |
| 429 | `capacity_limited` | Retry only after `retry_after_ms` and within job deadline. |
| 502/503 | `upstream_failure` / `cloud_not_ready` | Bounded retry with backoff, then `pending_upload`. |
| 504 | `inference_timeout` | Reconcile by `job_id`; if no result, queue without verdict. |

Transport timeout leaves job state unknown. The client first performs status
reconciliation; it must not create a new job ID to hide a timed-out request.
Retries use the same job ID and idempotency key. When the retry budget is
exhausted, the operator sees `Pending upload — no verdict available`.

## 5. Compatibility and contract changes

Additive optional fields are backward compatible. Renaming/removing a field,
changing enum meaning, changing signature canonicalization, or permitting full
frames requires a contract version change in the same PR as producer and
consumer updates. The legacy `cloud_qwen_dev` route and the old Pad-to-Jetson
contract are not compatible implementations of this API. A different LLM/VLM
may replace the default model without changing this contract when its adapter
preserves the schemas, fail-closed semantics, evidence fields, and timing.
