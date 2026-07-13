# Jetson Xavier NX Runner — API Contract

**Owner:** WS5 (`claude/ws5-xavier-runner-real-adapter`). **Consumed by:** WS4
(Pad LAN client) and Account A's WS3 (admin Jetson fleet/health screen).

**Status legend:** `[EXISTS]` = implemented in PR #51/#52 (unmerged, being
carried into `main` by WS5) and can be integrated against today. `[PLANNED]` =
does not exist yet; WS5 will add it in this round so WS4 has something real to
call, not just this doc's promise. `[MOCK]` = the current implementation is a
labeled mock (§ Mock/real labeling), not real VLM inference.

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
  "agent_version": "0.1.0"
}
```

`readiness_state` is one of the enum in § 3. In `JETSON_MOCK_MODE=true` (the
CI/dev default) these values are deterministic stand-ins, not sensor reads —
see § 4 for the labeling requirement. A real build reads `tegrastats`/`jtop`
for `temperature_c`/`throttling`; `disk_free_percent` on real hardware is not
yet wired (`None` today) — WS5 should fill this in the real-adapter PR.

### 1.2 `POST /infer` `[EXISTS]` `[MOCK — real adapter is WS5's core deliverable]`

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
- On rejection: `403` with `{"detail": "<reason>"}`, `reason` ∈
  `unpaired_caller | bad_signature`. A malformed request body (fails the § 2
  schema) currently surfaces as `403 invalid_request:<pydantic error>` — WS5
  should consider splitting this to `422` to distinguish "bad payload" from
  "bad auth", since callers (WS4) need to tell those apart to render the right
  Pad-side error. Flagging this as a contract nit, not blocking WS4 from
  building against the current behavior.
- **Fail-closed, unconditionally**: an unpaired caller or bad signature never
  falls through to any inference path, mock or real.

### 1.3 `POST /phase1/pair-loopback` `[EXISTS]` `[TEST-ONLY — never enable in production]`

Added in PR #52. Disabled unless `JETSON_PHASE1_LOOPBACK_PAIRING=true`, and
even then only accepts `127.0.0.1`/`::1` callers (`403 loopback_only`
otherwise). This exists solely for the same-device Phase 1 CV validation
harness. **Not a substitute for real LAN pairing** — see § 1.4.

### 1.4 Real LAN pairing endpoints `[PLANNED — gap WS5 must close]`

**This is the most important gap in this contract.** Today, USB pairing
(`PairingAgent.pair_usb`) and Wi-Fi pairing (`PairingAgent.pair_wifi`) exist
only as **in-process Python methods** — there is no HTTP endpoint a real
Android Pad can call over LAN to invoke them. The only HTTP-reachable pairing
path is the loopback-only Phase 1 harness (§ 1.3), which is explicitly
same-device and test-only.

WS4 (Pad LAN client) needs real endpoints. WS5 should add, following the
existing `/phase1/pair-loopback` pattern but LAN-scoped instead of
loopback-scoped:

```
POST /pair/usb
  body: {"pad_device_id": str, "pad_pubkey": str}
  -> 200 {"jetson_device_id", "jetson_pubkey", "pair_key", "pairing_path": "usb"}
  -> USB-path semantics per PairingAgent.pair_usb: physical connection is the
     proof of presence. If the Jetson can distinguish "request arrived over
     the USB gadget interface" from "request arrived over Wi-Fi LAN" at the
     network layer, enforce that distinction here; if it cannot (e.g. USB
     gadget Ethernet looks like any other NIC to the app), say so explicitly
     in the PR rather than silently accepting Wi-Fi callers on this endpoint.

POST /pair/wifi
  body: {"pad_device_id": str, "pad_pubkey": str, "confirmed_fingerprint": str}
  -> 200 {"jetson_device_id", "jetson_pubkey", "pair_key", "pairing_path": "wifi"}
  -> 403 {"detail": "pairing_window_closed"} | {"detail": "fingerprint_mismatch"}
  -> Only accepted while PairingAgent.pairing_window_open() is true (opened by
     a physical trigger on the Jetson — out of scope for the HTTP layer itself).
```

Re-pairing (either path) replaces the previous binding **immediately, no
grace period** — the old Pad's signed `/infer` calls start failing with
`bad_signature`/`unpaired_caller` the instant a new pairing completes. This is
existing `PairingAgent._establish` behavior; the new HTTP endpoints must not
change it.

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

## 4. Mock/real labeling requirement

Per the audit's ground rule (Overview § "Ground rule for every workstream"),
retained mock behavior must be impossible to mistake for real inference:

- `JETSON_MOCK_MODE` (default `true`) must gate which inference path runs —
  currently (`inference_server.run_inference`) it does **not** actually
  branch on this flag; the mock is unconditionally what runs. WS5's de-mock
  work must make this a real switch, log
  `"MOCK INFERENCE — NOT REAL QC JUDGMENT"` at call time when mock is active,
  and make mock mode unselectable in a config explicitly marked
  `APP_ENV=production` / `production` build.
- `PerPointResult.evidence` in mock mode should keep saying "mock qc-model
  inference for …" (already true today) so it is visually obvious in logs,
  UI, and stored results.

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
