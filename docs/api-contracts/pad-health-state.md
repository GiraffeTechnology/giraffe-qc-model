# Android Pad Health State — Architecture v2 Contract

**Contract version:** `2.0`

**Owner:** WS4 for Operator/Nano/cloud state; WS5 for Xavier health adapter

**Consumer:** WS3 Administrator health screen

**Implementation status on `main`:** `[PLANNED]`. Existing Android health state
is tied to the retired Operator MNN/Jetson architecture.

This contract is an Android-side state boundary, not a fourth inference API.
WS3 reads one immutable `PadHealthState`/`StateFlow` and does not poll three
systems independently. WS4 owns refresh, network policy, and persistence; WS5
maps `xavier-admin-runner-api.md` health into the Xavier section.

## 1. State shape

Wire names below are also the required serialized names when health is relayed
to the server for fleet visibility.

```json
{
  "schema_version": "2.0",
  "observed_at": "2026-07-14T03:04:05.678Z",
  "pad_device_id": "pad_hk_014",
  "workstation_id": "line3_station2",
  "operator_pipeline_readiness": "ready",
  "can_start_job": true,
  "nano_cv": {
    "status": "ready",
    "agent_version": "opaque-version",
    "pipeline_version": "opaque-version",
    "last_success_at": "2026-07-14T03:03:59.000Z",
    "last_error_code": null,
    "last_cv_duration_ms": 1140
  },
  "cloud_link": {
    "state": "healthy",
    "cloud_service": "reachable",
    "accepting_jobs": true,
    "current_network": "wifi",
    "active_job_network": null,
    "switch_deferred_until_job_end": false,
    "effective_uplink_mbps": 8.4,
    "rtt_ms": 88,
    "packet_loss_percent": 0.2,
    "sample_window_size": 3,
    "thresholds": {
      "min_uplink_mbps": 4.0,
      "max_rtt_ms": 300,
      "max_packet_loss_percent": 5.0,
      "wifi_return_min_uplink_mbps": 6.0,
      "wifi_return_sustain_seconds": 60
    },
    "threshold_breaches": [],
    "wifi_return_eligible_at": null,
    "last_probe_at": "2026-07-14T03:04:04.500Z",
    "last_real_transfer_at": "2026-07-14T03:03:52.000Z",
    "last_switch": null
  },
  "offline_queue": {
    "pending_upload_jobs": 0,
    "oldest_pending_since": null,
    "last_retry_at": null,
    "last_error_code": null
  },
  "xavier_admin": {
    "status": "ready",
    "runner_id": "xavier_admin_hk_01",
    "runtime_engine": "mnn",
    "adapter_mode": "real",
    "model_name": "qwen3-vl-4b",
    "model_loaded": true,
    "temperature_c": 58.2,
    "thermal_state": "normal",
    "disk_free_bytes": 34359738368,
    "last_recognition_latency_ms": 4310,
    "last_seen_at": "2026-07-14T03:04:04.900Z",
    "mock": false,
    "hardware_validation_status": "not_run"
  }
}
```

Missing/unmeasured numeric facts are `null`, not zero and not a placeholder.
Each subsystem keeps its own observation time; the top-level `observed_at` is
when the aggregate snapshot was emitted.

## 2. Enums and submit gate

### 2.1 Operator pipeline readiness

| Value | Meaning | `can_start_job` |
|---|---|---:|
| `ready` | Nano CV ready, a healthy link selected, cloud reachable and accepting jobs. | `true` |
| `degraded_queue_available` | CV ready but both usable cloud paths are currently below policy/unavailable; capture may be queued only through an explicit pending-upload flow. | `false` for live inference |
| `cv_unavailable` | Nano CV/crop pipeline cannot produce valid crops. | `false` |
| `cloud_unreachable` | Selected link works but inference health is unreachable/not accepting. | `false` |
| `offline` | Neither Wi-Fi nor cellular can reach the service. | `false` |
| `unknown` | Required observations are absent or stale. | `false` |

`can_start_job` means a job can start with an expectation of live cloud
recognition. An explicit queue-only capture flow may be offered in
`degraded_queue_available`, but the UI must say `Pending upload — no verdict
available`. Xavier health never changes this Operator gate.

### 2.2 Nano CV

`nano_cv.status` is `starting | ready | degraded | unavailable | unknown`.
`last_cv_duration_ms` is a real completed CV/crop duration only. Mock/fixture
timing must not populate it in a production health snapshot.

### 2.3 Cloud/link

- `cloud_link.state`: `healthy | degraded | switching | offline | unknown`.
- `cloud_service`: `reachable | unreachable | unknown`.
- `current_network`: `wifi | cellular | none | unknown`.
- `threshold_breaches` values:
  `uplink_below_threshold | rtt_above_threshold |
  packet_loss_above_threshold | cloud_not_accepting | no_cellular_available`.

`last_switch`, when present, is:

```json
{
  "from": "wifi",
  "to": "cellular",
  "reason": "uplink_below_threshold",
  "at": "2026-07-14T03:04:00.000Z"
}
```

### 2.4 Xavier Administrator node

`xavier_admin.status` is `not_configured | connecting | ready | degraded |
unreachable | unknown`. It maps directly from
`xavier-admin-runner-api.md`; it must report `runtime_engine=mnn` and
the configured `model_name` truthfully. Architecture v2 defaults that field to
`qwen3-vl-4b`, but consumers must not use a Qwen-specific enum or assume the
product is tied to that provider. This state gates only Administrator
local-recognition actions.

If `mock=true`, WS3 must show the exact banner `MOCK INFERENCE — NOT REAL QC
JUDGMENT`. A production configuration must never emit a mock-ready state.

## 3. Network policy state machine

Site configuration supplies thresholds; defaults are:

- effective uplink below 4 Mbps for a 3-sample window, or
- RTT above 300 ms, or
- packet loss above 5%.

Any sustained breach on Wi-Fi triggers a switch attempt to cellular before a
new job starts. If cellular is unavailable or also below threshold, live submit
is blocked and the explicit offline queue path is offered. Every breach and
switch is persisted in telemetry with the observed metrics and reason.

The moving estimate combines the signed probe endpoint with actual crop
transfers; real transfers have priority over probes while fresh. A probe is a
network measurement, never an inference measurement.

There is no mid-job flapping:

1. At upload start, set `active_job_network` to the selected network.
2. Hold that network for the request/retry attempt. A newly observed preference
   sets `switch_deferred_until_job_end=true`.
3. After the job ends or enters `pending_upload`, apply the deferred switch.
4. Return from cellular to Wi-Fi only after effective Wi-Fi uplink remains
   above 6 Mbps for 60 continuous seconds and other thresholds are healthy.

## 4. Freshness and failure rules

Default freshness limits are implementation configuration and must be emitted
with telemetry. As a contract minimum:

- a cloud health observation older than two health-poll intervals becomes
  `cloud_service=unknown` and fails closed;
- a Nano heartbeat older than two heartbeat intervals becomes
  `nano_cv.status=unknown`;
- a Xavier observation older than two poll intervals becomes `unreachable`.

Refresh failures retain the last values only for diagnostic display and mark
them stale; stale facts cannot keep `can_start_job=true`.

Offline queue records are durable across app restart and include job ID,
capture/CV/upload timestamps, retry count, next retry time, selected network,
and last error. Queue records contain crops and minimal metadata only; they do
not contain a fabricated result.

## 5. WS3 presentation requirements

The Administrator health screen presents three separately labeled panels:

1. **Operator Nano CV** — readiness, last real CV duration, last error.
2. **Cloud connection** — current network, cloud reachability, three metrics,
   threshold breaches, last switch, and pending-upload count.
3. **Administrator Xavier MNN** — model loaded, thermal/disk, last real local
   latency, mock label, and hardware-validation status.

`unknown`, stale, pending, and unvalidated states are displayed literally.
The screen must not collapse Nano and Xavier into a generic “Jetson healthy”
indicator or show Xavier MNN health as Operator inference readiness.

## 6. Server relay (optional fleet visibility)

WS3 on the same Pad reads the `StateFlow` directly. If a deployment relays the
snapshot to the backend, use one tenant-authenticated endpoint
`POST /api/qc/pads/{pad_device_id}/health` with this exact JSON payload and make
the relay best-effort. Relay failure affects fleet visibility only; it cannot
override local fail-closed readiness. This relay endpoint is `[PLANNED]` and is
not a prerequisite for the local WS3 screen.
