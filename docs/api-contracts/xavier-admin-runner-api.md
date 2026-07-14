# Xavier NX Administrator Runner API — Architecture v2 Contract

**Contract version:** `2.0`

**Owner:** WS5 (`claude/ws5-xavier-runner-real-adapter`)

**Consumers:** Pad Administrator workflows, WS3 health screen through
`pad-health-state.md`, and WS8 CV pre-analysis

**Implementation status on `main`:** `[PLANNED]`. The existing Xavier runner is
a Pad/Operator-oriented, llama.cpp-shaped implementation and does not satisfy
this contract.

The Xavier NX is the Administrator-side local recognition node. It runs
classical CV followed by a configured MNN VLM provider for authoring and
qualification workflows. The Architecture v2 deployment default is
`qwen3-vl-4b`; it is a replaceable provider default, not the product identity
or an ecosystem lock-in. The Xavier is not in the production Operator path and
is not a fallback when the Operator cloud request fails.

## 1. Transport and authentication

The service listens on an administrator LAN endpoint configured per site. TLS
is required outside loopback. Every endpoint except an optional process-only
`/livez` requires an administrator-device bearer token plus a detached Ed25519
signature using the same header names and replay window as
`cloud-inference-api.md`, but with this domain separator:

```text
QC-XAVIER-ADMIN-V1
<UPPERCASE_METHOD>
<PATH>
<X-QC-Timestamp>
<X-QC-Nonce>
<X-QC-Content-SHA256>
<request_id-or-empty>
```

Each displayed line is terminated by one LF byte, including the final line.
For a bodyless health request, the content digest is SHA-256 of an empty byte
string and the request ID line is empty.

The signed principal identifies tenant, administrator device, and administrator
identity. Request-body `tenant_id` or actor identity is never authoritative.
Provisioning/pairing the key is a deployment concern; it must be complete before
the service can report `readiness: ready`.

## 2. Endpoints

| Method and path | Purpose |
|---|---|
| `GET /api/v2/admin-runner/health` | Live model/runtime, thermal, disk, CV, and last-call health. |
| `POST /api/v2/admin-runner/recognitions` | Batched local recognition for one administrator workflow request. |
| `GET /api/v2/admin-runner/recognitions/{request_id}` | Idempotent reconciliation after a client timeout. |

### 2.1 Health

```json
{
  "schema_version": "2.0",
  "runner_id": "xavier_admin_hk_01",
  "agent_version": "0.3.0",
  "observed_at": "2026-07-14T03:04:05.678Z",
  "readiness": "ready",
  "service_up": true,
  "runtime": {
    "engine": "mnn",
    "adapter_mode": "real",
    "model_name": "qwen3-vl-4b",
    "model_revision": "opaque-model-revision",
    "model_loaded": true,
    "loaded_at": "2026-07-14T02:55:00.000Z"
  },
  "cv_pipeline": {
    "status": "ready",
    "package_version": "opaque-version"
  },
  "device": {
    "temperature_c": 58.2,
    "thermal_state": "normal",
    "throttling": false,
    "disk_free_bytes": 34359738368,
    "disk_total_bytes": 128849018880
  },
  "last_recognition": {
    "status": "completed",
    "finished_at": "2026-07-14T03:03:59.120Z",
    "latency_ms": 4310
  },
  "hardware_validation": {
    "status": "not_run",
    "evidence_ref": null
  },
  "mock": false
}
```

`readiness` is `starting | ready | degraded | not_ready`. Recognition is
accepted only in `ready`. `thermal_state` is `normal | warm | throttled |
unknown`. An unavailable sensor is `null`/`unknown`, never a fabricated healthy
number. `latency_ms` is null until a real model call completes; mock HTTP timing
must not populate it.

`adapter_mode` is `real | mock`. If mock is retained for CI, every response and
log contains `MOCK INFERENCE — NOT REAL QC JUDGMENT`, `mock=true`, and
`APP_ENV=production` with mock selected must refuse startup. A real adapter
implementation with `hardware_validation.status=not_run` is not evidence that
real-device inference has passed.

### 2.2 Recognition request

The request is `multipart/form-data`: one canonical JSON `manifest` part and
one or more `image/*` parts. Administrator workflows may use source/reference
images; the Operator crop-only rule does not apply here.

```json
{
  "schema_version": "2.0",
  "request_id": "adminrec_01J2ABCDEF",
  "workflow": "authoring_validation",
  "standard_revision_id": "rev_01J2STANDARD",
  "bundle_version": "2026.07.14-3",
  "images": [
    {
      "image_id": "reference_front",
      "part": "reference_front.jpg",
      "sha256": "<64-lowercase-hex>",
      "content_type": "image/jpeg",
      "encoded_bytes": 412300
    }
  ],
  "detection_points": [
    {
      "point_code": "front_rhinestones",
      "image_id": "reference_front",
      "label": "Front rhinestones",
      "description": "Check presence and attachment",
      "expected_value": "24",
      "pass_criteria": "all expected rhinestones present and attached",
      "severity": "major",
      "regions": [{"x": 0.12, "y": 0.20, "w": 0.32, "h": 0.28}],
      "expected_features": {"rhinestone_count": 24},
      "cv_config": {
        "analyzers": ["rhinestone_count"],
        "parameters": {"min_radius_px": 3, "max_radius_px": 16}
      }
    }
  ]
}
```

`workflow` is `authoring_validation | qualification_review | admin_recheck`.
The arrays must be non-empty and all referenced image IDs must exist. Region
coordinates are normalized `[0,1]`. `expected_features` and `cv_config` are
optional WS6/WS8 extensions; their absence must preserve pre-WS8 prompt input.

Before each MNN call, configured WS8 analyzers run deterministically. Their JSON
is inserted into the VLM prompt inside a delimited `CV_PREANALYSIS_JSON` block.
If CV fails, the response records `cv_status: failed` and the VLM call proceeds
without CV context.

### 2.3 Recognition response

```json
{
  "schema_version": "2.0",
  "request_id": "adminrec_01J2ABCDEF",
  "status": "completed",
  "point_results": [
    {
      "point_code": "front_rhinestones",
      "result": "pass",
      "confidence": 0.91,
      "evidence": "All expected positions are visible in the marked region.",
      "evidence_regions": [{"x": 0.12, "y": 0.20, "w": 0.32, "h": 0.28}],
      "cv_status": "completed",
      "cv_analysis": {
        "analyzer": "rhinestone_count",
        "count": 24,
        "deviations": []
      }
    }
  ],
  "runtime": {
    "engine": "mnn",
    "model_name": "qwen3-vl-4b",
    "model_revision": "opaque-model-revision",
    "adapter_mode": "real"
  },
  "timing": {
    "request_received_at": "2026-07-14T03:04:05.678Z",
    "cv_started_at": "2026-07-14T03:04:05.700Z",
    "cv_completed_at": "2026-07-14T03:04:06.010Z",
    "inference_started_at": "2026-07-14T03:04:06.020Z",
    "inference_completed_at": "2026-07-14T03:04:10.100Z",
    "response_sent_at": "2026-07-14T03:04:10.120Z"
  },
  "mock": false
}
```

`result` is `pass | fail | uncertain`. These are administrator workflow
recognitions, not Operator production verdicts. Consumers must retain the model
revision, prompt/schema revision, CV evidence, and administrator identity in
the audit record.

## 3. Idempotency and failures

`request_id` is the `Idempotency-Key`. Same ID plus same signed digest returns
the original status/result; same ID plus different digest returns
`409 idempotency_conflict`.

Errors use the envelope from `cloud-inference-api.md`. Required codes are:

| HTTP | Code | Meaning |
|---:|---|---|
| 401/403 | `authentication_required`, `bad_signature`, `device_not_authorized` | No recognition runs. |
| 409 | `idempotency_conflict` | Request identity was reused with different content. |
| 413 | `image_too_large` | Site-configured request limit exceeded. |
| 422 | `invalid_request`, `unsupported_schema`, `image_digest_mismatch` | Payload is not executable. |
| 429 | `runner_busy` | Retry after the returned bounded delay. |
| 503 | `model_not_loaded`, `runtime_not_ready`, `thermal_block` | No mock fallback; retry only after health becomes ready. |
| 504 | `recognition_timeout` | Reconcile by `request_id`; absent result means no recognition. |

Per-point parse errors may return `uncertain` for only that point if the MNN
call itself completed and auditable raw output is retained. A runner/runtime
failure affecting the batch fails the request; it never fills points with
synthetic pass/fail values.

## 4. Relationship to legacy contracts

`jetson-runner-api.md` describes the superseded Architecture v1 Operator
Pad-to-Xavier path and its llama.cpp-shaped adapter. It is not an alias for this
API. WS5 may reuse implementation pieces, but must expose the endpoints,
runtime identity, health truthfulness, and MNN model in this contract.

The provider boundary is model-agnostic: another MNN-compatible VLM may replace
the default without changing the HTTP contract when it preserves schemas,
evidence semantics, fail-closed behavior, and truthful runtime identity.
