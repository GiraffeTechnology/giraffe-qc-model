# Jetson Xavier NX Runner — API Contract

**Owner:** WS5 (`claude/ws5-xavier-runner-real-adapter`). **Consumed by:** WS4
(Pad LAN client) and Account A's WS3 (admin Jetson fleet/health screen).

**Status legend:** `[EXISTS]` = implemented (PR #51/#52 content, plus WS5's
de-mock/real-adapter/pairing-endpoint round) and can be integrated against
today. `[PLANNED]` = does not exist yet. `[MOCK]` = the current
implementation is a labeled mock (§ Mock/real labeling), not real VLM
inference.

**Update (WS5 round):** § 1.4's pairing endpoints and § 4's mock-mode gating
were `[PLANNED]` gaps when this doc was first published (Step 0) and are now
`[EXISTS]` — implemented in the same PR as this update. Both sections below
reflect the as-built state, not the original gap description.

There are **two separate HTTP surfaces** — do not conflate them:

1. **Jetson LAN surface** (this device, port `8600` by default) — the Pad
   talks to this directly over LAN. The Server is never in this path.
2. **Server sync surface** (`/api/qc/jetson/*` on the qc-model Server) — the
   Pad relays pairing/health to the Server *after the fact* so Admin Studio
   has fleet visibility. Inference results do **not** flow through here.

```text
Pad ──LAN, signed──► Jetson  (surface 1: pairing, /infer, /health)
Pad ──sync, when reachable──► Server  (surface 2: /api/qc/jetson/*)
```

Pairing is **floor first, sync later** — surface 1 must work with the Server
completely unreachable; surface 2 is best-effort fleet visibility, not a
dependency for inspection.

## 1. Jetson LAN surface (runs on the Jetson, `jetson_runner/`)

### 1.1 `GET /health` `[EXISTS]` `[MOCK by default]`

No auth (LAN-only, never internet-exposed — enforce at the network layer, not
in application code). Returns:

```json
{
  "service_up": true,
  "model_loaded": true,
  "temperature_c": 61.5,
  "throttling": false,
  "disk_free_percent": 72.0,
  "last_inference_latency_ms": 340,
  "readiness_state": "jetson_ready",
  "jetson_device_id": "jetson-a1b2c3d4",
  "agent_version": "0.2.0",
  "mock": true,
  "adapter_name": "mock",
  "model_name": "mock-deterministic"
}
```

`readiness_state` is one of the enum in § 3. `mock` is explicit (added in the
WS5 round) so callers never have to infer mock-vs-real from other fields. In
`JETSON_MOCK_MODE=true` these values are deterministic stand-ins, not sensor
reads. A real build reads `tegrastats`/`jtop` for `temperature_c`/
`throttling` when the optional `jtop` package is installed; `disk_free_percent`
on real hardware is still not wired (`None`) — a real deployment must not
treat that as "disk is fine," it means "not measured yet."

`model_loaded` under a real adapter reflects `adapter.is_ready()` (a live
`GET {llama_server_url}/health` check), not a cached/assumed value.

### 1.2 `POST /infer` `[EXISTS]` `[MOCK by default; real path is an unvalidated scaffold, see § 4]`

Request envelope (what the Pad POSTs):

```json
{
  "pad_device_id": "pad-1a2b3c",
  "signature": "<hex hmac-sha256>",
  "request": { /* InferenceRequest, § 2 */ }
}
```

- `signature` = `HMAC-SHA256(pair_key, canonical_json(request))`, where
  `canonical_json` is `json.dumps(request, sort_keys=True, separators=(",", ":"))`
  (see `jetson_runner/app/signing.py`). `pair_key` is the per-pair secret
  established at pairing (§ 1.4) — **never** a global/shared secret.
- On success: `200` with an `InferenceResponse` (§ 2).
- On rejection, status now distinguishes the failure kind (resolved in the
  WS5 round — was uniformly `403` at Step 0):
  - `403 {"detail": "unpaired_caller"}` / `403 {"detail": "bad_signature"}` —
    auth failures.
  - `422 {"detail": "invalid_request:<pydantic error>"}` — payload fails the
    § 2 schema.
  - `503 {"detail": "runtime_not_ready"}` — real adapter selected but not
    ready (backend unreachable / no model loaded). Never falls through to
    mock, never lets a doomed call through.
- **Fail-closed, unconditionally**: an unpaired caller, bad signature, or
  not-ready real backend never falls through to any inference path.
- A per-detection-point backend/parse failure in the real adapter (once one
  is actually certified — see § 4) downgrades only that point to
  `"uncertain"`, not the whole request.

### 1.3 `POST /phase1/pair-loopback` `[EXISTS]` `[TEST-ONLY — never enable in production]`

Added in PR #52. Disabled unless `JETSON_PHASE1_LOOPBACK_PAIRING=true`, and
even then only accepts `127.0.0.1`/`::1` callers (`403 loopback_only`
otherwise). This exists solely for the same-device Phase 1 CV validation
harness. **Not a substitute for real LAN pairing** — see § 1.4.

### 1.4 Real LAN pairing endpoints `[EXISTS — implemented in the WS5 round]`

```
POST /pair/usb
  body: {"pad_device_id": str, "pad_pubkey": str}
  -> 200 {"jetson_device_id", "jetson_pubkey", "pair_key", "pairing_path": "usb"}
  -> 422 {"detail": "pad_device_id_and_pad_pubkey_required"}

POST /pair/wifi
  body: {"pad_device_id": str, "pad_pubkey": str, "confirmed_fingerprint": str}
  -> 200 {"jetson_device_id", "jetson_pubkey", "pair_key", "pairing_path": "wifi"}
  -> 403 {"detail": "pairing_window_closed"} | {"detail": "fingerprint_mismatch"}
  -> 422 {"detail": "pad_device_id_and_pad_pubkey_and_confirmed_fingerprint_required"}
  -> Only accepted while PairingAgent.pairing_window_open() is true (opened by
     a physical trigger on the Jetson — out of scope for the HTTP layer itself).
```

**Known limitation, not silently papered over:** `/pair/usb` currently
accepts *any* caller that reaches it — the HTTP layer cannot distinguish "this
request arrived over the USB gadget interface" from "this request arrived
over Wi-Fi LAN" (both look like a normal NIC to the FastAPI app). The
physical-presence guarantee that makes the USB path meaningful (per
`PairingAgent.pair_usb`'s docstring: "the physical cable is the
authorization") is therefore enforced, if at all, by whatever network
topology puts the USB gadget interface on its own unroutable link at
deployment time — not by this handler. WS4/deployment should not assume
`/pair/usb` is LAN-unreachable unless that topology is actually in place;
verifying/enforcing it is unresolved and should be tracked as a follow-up,
not assumed solved by this endpoint's name.

Re-pairing (either path) replaces the previous binding **immediately, no
grace period** — the old Pad's signed `/infer` calls start failing with
`bad_signature`/`unpaired_caller` the instant a new pairing completes. This is
existing `PairingAgent._establish` behavior, unchanged by the new endpoints.

## 2. Inference request/response schema (`src/qc_model/jetson/contract.py`)

Stateless per request — every `InferenceRequest` carries the full
detection-point spec inline (no bundle caching on the Jetson, so there is no
Pad↔Jetson version-skew state to manage).

```jsonc
// InferenceRequest (Pad -> Jetson, inside the signed "request" field)
{
  "job_id": "string",
  "standard_revision_id": "string",
  "bundle_version": "string",           // optional, default ""
  "image": "string",                     // reference/URI or inline-encoded frame; bytes never touch the Server
  "detection_points": [                  // must be non-empty
    {
      "point_code": "string",
      "label": "string",                 // optional
      "description": "string",           // optional
      "method_hint": "string",           // optional
      "expected_value": "string",        // optional
      "pass_criteria": "string",         // optional
      "severity": "major",               // optional, default "major"
      "regions": [ {"image_id": "string", "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0} ]
    }
  ]
}

// InferenceResponse (Jetson -> Pad) — evidence, NOT a verdict.
// The Server's S4 recomputation remains the authoritative pass/fail.
{
  "job_id": "string",
  "per_point_results": [
    {
      "point_code": "string",
      "result": "pass | fail | uncertain",
      "confidence": 0.0,
      "evidence": "string"
    }
  ]
}
```

## 3. Readiness state enum (`src/qc_model/jetson/constants.py`)

Shared vocabulary between Jetson, Pad, and Server — do not invent new state
strings on either side.

| State | Meaning | Submit allowed? |
|---|---|---|
| `jetson_ready` | Jetson connected & ready | **yes** — the only submittable state |
| `jetson_connecting` | Jetson connecting... | no |
| `jetson_unreachable` | offline mode — inspection blocked | no |
| `no_standard_installed` | No standard installed | no |
| `no_sku_selected` | No SKU selected | no |

Fail-closed rule (binding on every consumer, not just WS5's own code): when
`readiness_state != jetson_ready`, the Pad's real submit action must be
disabled — no silent fallback to a mock/pass result. This is WS4's § "fail-
closed gate" requirement, but the state values it must gate on come from here.

## 4. Mock/real labeling requirement `[EXISTS — implemented in the WS5 round]`

Per the audit's ground rule (Overview § "Ground rule for every workstream"),
retained mock behavior must be impossible to mistake for real inference:

- `JETSON_MOCK_MODE` now actually gates which of two `InferenceAdapter`
  implementations runs (`jetson_runner/app/adapters/`): `mock` or
  `llama_cpp`. Every mock-served `/infer` call logs
  `"MOCK INFERENCE — NOT REAL QC JUDGMENT"` at WARNING.
- `RunnerConfig` **raises** `MockModeNotAllowedInProduction` at construction
  if `JETSON_MOCK_MODE=true` under `APP_ENV=production` — a misconfigured
  production deployment refuses to start rather than silently running mock.
  `mock_mode` defaults to `false` under `APP_ENV=production`, `true`
  otherwise, so no special config is needed for the safe default.
- `PerPointResult.evidence` in mock mode keeps saying "mock qc-model
  inference for …" so it is visually obvious in logs, UI, and stored results.

**The `llama_cpp` adapter is an unvalidated scaffold, not a certified
backend.** It has never been run against a real model or real Xavier NX
hardware — the JetPack 5.1.x reflash + llama-server setup it depends on is a
pending Phase 1.5 device-side step (see `JETSON_NX_RUNTIME_FEASIBILITY.md`).
Selecting `JETSON_MOCK_MODE=false` today gives you a real, complete,
fail-closed code path (backend readiness check → per-point HTTP call → strict
JSON parse → per-point `uncertain` on any failure) — not measured accuracy or
latency. Do not read "the adapter exists" as "real inference is certified."

## 5. Server sync surface (`/api/qc/jetson/*`, `src/api/jetson_router.py`) `[EXISTS]`

Already implemented in PR #51 — WS4 does not need to build this, and Account
A's WS3 admin screen can bind directly to it.

| Method + path | Purpose |
|---|---|
| `POST /api/qc/jetson/runners` | Provision a Jetson (device id + pubkey fingerprint) |
| `GET /api/qc/jetson/runners` | List runners for a tenant (fleet view) |
| `GET /api/qc/jetson/runners/{jetson_device_id}` | One runner's current state |
| `POST /api/qc/jetson/bindings` | Pad relays a completed pairing binding (offline-tolerant; §1:1, re-pair replaces) |
| `POST /api/qc/jetson/runners/{jetson_device_id}/unpair` | Admin-initiated unpair |
| `POST /api/qc/jetson/runners/{jetson_device_id}/health` | Pad relays a Jetson health snapshot (§1) |
| `POST /api/qc/jetson/readiness` | Resolve § 3's readiness state + `can_submit_inspection` from raw inputs |
| `POST /api/qc/jetson/inference/validate` | Validate a payload against § 2's schema (dev/test helper) |

The Server is **not** in the inference path — these endpoints exist purely
for fleet visibility and offline-tolerant pairing-state sync. See
`pad-jetson-health-state.md` for how the Pad decides when/what to relay here.
