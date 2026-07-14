# Xavier NX Administrator MNN runner

This headless service provides local visual recognition for Administrator
authoring, qualification, and recheck workflows. Under Architecture v2 it is
not part of the production Operator path and is never an Operator cloud
fallback. The API contract is
`docs/api-contracts/xavier-admin-runner-api.md`.

The runtime is provider-neutral. `qwen3-vl-4b` is the replaceable default VLM
configuration; Giraffe is not a Qwen ecosystem product. HTTP clients depend on
the MNN adapter contract and the reported model identity, so a compatible
MNN-exported VLM can be selected through deployment configuration.

## Real and mock modes

`XAVIER_INFERENCE_MODE=real` is the default in every environment. It loads a
persistent model through `libgiraffe_mnn_bridge.so`; readiness is true only
when the live native model handle reports loaded. Missing bridge/model/runtime
state fails closed and never falls back to mock.

`XAVIER_INFERENCE_MODE=mock` exists only for tests. Every mock response,
per-point evidence record, and request log contains:

```text
MOCK INFERENCE — NOT REAL QC JUDGMENT
```

Mock mode is refused when `APP_ENV=production`. The legacy explicit
`JETSON_MOCK_MODE` input remains temporarily supported during manifest
migration, but mock is never an implicit default.

## Endpoints

| Method + path | Purpose |
|---|---|
| `GET /livez` | Process liveness only; no runtime-readiness claim. |
| `GET /api/v2/admin-runner/health` | Signed model, device, CV, and validation health. |
| `POST /api/v2/admin-runner/recognitions` | Signed multipart Administrator recognition. |
| `GET /api/v2/admin-runner/recognitions/{request_id}` | Signed idempotent reconciliation. |

The older `/health`, `/pair/*`, and `/infer` routes are migration-only
Architecture v1 endpoints. New Operator code must use the cloud inference
contract, not these routes.

## Authentication

Provision bearer-token and Ed25519 public-key records as JSON keyed by token:

```bash
export XAVIER_ADMIN_CREDENTIALS_JSON='{
  "opaque-token": {
    "tenant_id": "tenant-1",
    "subject": "admin-device-1",
    "key_id": "key-1",
    "public_key": "BASE64_RAW_ED25519_PUBLIC_KEY"
  }
}'
```

All v2 routes except `/livez` require the detached signature defined by the
contract. Production readiness remains `not_ready` until credentials and the
live model are both available.

## Real runtime configuration

```bash
export APP_ENV=production
export XAVIER_INFERENCE_MODE=real
export XAVIER_MNN_BRIDGE_LIBRARY=/opt/giraffe/lib/libgiraffe_mnn_bridge.so
export XAVIER_MNN_MODEL_DIR=/opt/giraffe/models/qwen3-vl-4b-mnn
export XAVIER_MNN_MODEL_NAME=qwen3-vl-4b  # configurable default, not a required provider
python -m jetson_runner.app.main
```

Build the bridge against the exact pinned MNN SDK:

```bash
cmake -S jetson_runner/native -B build/xavier-mnn \
  -DMNN_ROOT=/opt/mnn-pinned
cmake --build build/xavier-mnn --config Release
```

The source and CI environment do not contain the Xavier SDK or weights. Follow
`HARDWARE_VALIDATION.md`; do not describe this path as hardware-validated until
its evidence checklist has been completed and reviewed.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `XAVIER_INFERENCE_MODE` | `real` | `real` or test-only `mock`. |
| `XAVIER_MNN_BRIDGE_LIBRARY` | `/opt/giraffe/lib/libgiraffe_mnn_bridge.so` | Native provider-neutral MNN bridge. |
| `XAVIER_MNN_MODEL_DIR` | `/opt/giraffe/models/qwen3-vl-4b-mnn` | Configured exported VLM bundle. |
| `XAVIER_MNN_MODEL_NAME` | `qwen3-vl-4b` | Reported model name; Qwen is only the default. |
| `XAVIER_ADMIN_CREDENTIALS_JSON` | `{}` | Provisioned Administrator credentials. |
| `XAVIER_MAX_REQUEST_BYTES` | `20971520` | Total uploaded image-byte limit. |
| `XAVIER_HARDWARE_VALIDATION_STATUS` | `not_run` | Manual evidence state; `passed` requires an evidence reference. |
| `JETSON_BIND_HOST` / `JETSON_BIND_PORT` | `0.0.0.0` / `8600` | Site LAN bind. TLS termination is required outside loopback. |

## Current limitations

- The native bridge must be compiled and exercised on the approved Xavier
  image; this has not been performed in CI.
- WS8 owns OpenCV pre-analysis execution. Until that work is merged, health
  reports `cv_pipeline.status=not_configured`; supplied CV evidence is carried
  into prompts but is not fabricated locally.
- The in-memory idempotency/replay stores are process-local. Durable encrypted
  persistence is required before cross-restart reconciliation can be claimed.
- TLS termination and credential provisioning are deployment responsibilities;
  they are not simulated by this repository.
