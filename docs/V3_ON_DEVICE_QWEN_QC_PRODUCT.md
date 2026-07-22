# V3 On-Device QWEN QC Product Architecture

## Product Goal

Deliver a single Android APK for apparel and textile quality control (QC) inspection that:

- Installs on a standard Android device with no root and no separate server
- Uses **Qwen2-VL-2B-Instruct-MNN** running on-device via the **MNN inference framework** as the primary inspection engine
- Operates fully offline by default — cloud connectivity is optional and dual-gated
- Meets the latency and memory budget of Snapdragon 8 Gen class hardware

The target hardware profile is:

| Parameter | Value |
|-----------|-------|
| SoC | Snapdragon 8 Gen |
| RAM | 8 GB |
| Storage | 128 GB |
| Model | Qwen2-VL-2B-Instruct-MNN (INT4) |
| Estimated runtime memory | ~3–4 GB |

The INT4-quantized 2B model is viable on this hardware. Larger models or FP16 weights are out of scope for v3.

---

## Engine Modes

The system is configured via the `QC_ENGINE_MODE` environment variable. Three modes are defined:

### 1. `cloud_qwen_dev` (temporary)

- Routes all inspection requests to the cloud Qwen API
- Used for development and validation before the physical Android test device arrives
- Not intended for production; should be disabled once on-device testing begins
- Allows iterating on schema, parser, and prompt logic without hardware

### 2. `on_device_first` (final architecture)

- On-device MNN inference is the **primary engine**
- Cloud fallback is available only when explicitly enabled and only for uncertain results
- This is the shipping architecture
- Offline inspection is fully supported

### 3. `backend_proxy` (specific use cases only)

- Cloud Qwen is the primary engine
- On-device MNN is not used
- Reserved for use cases where network connectivity is guaranteed and on-device latency budget cannot be met (e.g., bulk audit workstations)
- Not the default; requires explicit configuration

---

## Inspection Flow

```
Capture image
     │
     ▼
Standard photo + QC point config loaded
     │
     ▼
On-device MNN inference (Qwen2-VL-2B-Instruct-MNN)
     │
     ▼
Parser validates strict JSON schema
     │
     ├─ schema valid ──────────────────────────────────────┐
     │                                                     │
     └─ schema invalid / uncertain                         │
              │                                            │
              ▼                                            ▼
     Optional cloud fallback               Result display (pass / fail /
     (if QWEN_CLOUD_ENABLED +              review_required)
      ALLOW_SEND_IMAGES_TO_CLOUD_QWEN)           │
              │                                  │
              ▼                                  ▼
     Cloud result merged             Optional backend sync
     (cannot override fail)          (audit / fleet reporting)
```

Steps in detail:

1. **Capture** — camera captures the production garment image
2. **QC point config** — standard reference photo and per-point inspection criteria are loaded
3. **On-device inference** — MnnQwenInspector runs Qwen2-VL-2B-Instruct-MNN via MNN JNI
4. **Parser** — output is validated against the strict JSON schema; malformed output is rejected
5. **Result display** — one of `pass`, `fail`, or `review_required` is shown to the operator
6. **Cloud fallback** (optional) — triggered only if the result is uncertain and both cloud guards are enabled
7. **Backend sync** (optional) — result, metadata, and audit trail pushed to backend when connectivity is available

---

## Safety Policy

### Fail-Closed

The system is designed to fail closed. An uncertain or degraded result is never silently promoted to a pass:

| Condition | Result |
|-----------|--------|
| On-device inference succeeds, defect found | `fail` |
| On-device inference succeeds, no defect found | `pass` |
| Output fails JSON schema validation | `review_required` |
| On-device timeout | `review_required` |
| Model not provisioned | `review_required` |
| Confidence below threshold | `review_required` (or cloud fallback if enabled) |

`review_required` always routes the item to a human inspector. It never becomes an automatic pass.

### §4.5.4: `on_device_fail_is_final=true`

When the on-device engine returns `fail`, that result is **final**:

- Cloud fallback is **not called**, even if cloud is enabled
- The backend **cannot override** a device `fail` to `pass`
- This rule exists to prevent a misconfigured or compromised cloud endpoint from clearing defective items

---

## Privacy Policy

### Local-Only Default

All inference runs on-device. No image data leaves the device unless the operator has explicitly enabled cloud transmission.

### Dual Guards for Cloud Image Transmission

Sending images to the cloud Qwen API requires **both** of the following to be set:

| Guard | Purpose |
|-------|---------|
| `QWEN_CLOUD_ENABLED=true` | Enables cloud API connectivity at all |
| `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true` | Explicitly permits image data to leave the device |

If either guard is absent or false, images remain on-device regardless of network availability.

### `contains_pii` Flag

Assets in the Giraffe CAP asset registry carry a `contains_pii` boolean flag. Assets with `contains_pii=true` are never eligible for cloud transmission, independent of the dual-guard setting.

---

## Backend Role

The backend is **not** the primary inspection engine. Its responsibilities are limited to:

| Role | Description |
|------|-------------|
| Audit trail | Stores inspection outcomes with timestamps and device ID |
| Fleet reporting | Aggregates pass/fail/review_required rates across devices |
| CAP asset registry | Manages Giraffe standard reference photos and QC point configs |
| Cloud fallback | Accepts cloud Qwen inference requests when explicitly enabled |

The backend does not make primary pass/fail decisions. It receives results that the device has already determined.

---

## Implementation Status

### Implemented (Simulated Environment)

The following components are implemented and tested in the simulated/CI environment without requiring a physical device:

| Component | Status |
|-----------|--------|
| Strict JSON output schema | Implemented |
| Schema parser and validator | Implemented |
| Inspection router (`on_device_first` / `cloud_qwen_dev` / `backend_proxy`) | Implemented |
| FakeOnDeviceQwenInspector (stub for unit tests) | Implemented |
| FakeCloudQwenInspector (stub for unit tests) | Implemented |
| FastAPI backend endpoints (inspection, audit, fleet, asset registry) | Implemented |
| Android skeleton (MnnQwenInspector.kt with stub JNI) | Implemented |
| §4.5.4 fail-is-final logic (router level) | Implemented |
| Dual privacy guards (router level) | Implemented |
| Python unit/integration test suite (166+ tests) | Implemented |

### Requires Physical Android Test Device

The following cannot be validated without hardware:

| Component | Blocker |
|-----------|---------|
| Real MnnQwenInspector JNI (`nativeRunInference()`) | Requires MNN native libs on target ABI |
| Cold-start load time (budget: ≤30s) | Requires Snapdragon hardware |
| p50 / p95 per-image latency (budget: ≤10s p95) | Requires Snapdragon hardware |
| Peak memory measurement (budget: ≤6 GB) | Requires Android profiler on device |
| Full capture → result APK install and run | Requires physical device |
| Offline mode validation (no network calls) | Requires device with WiFi disabled |

See `MNN_DEVICE_TEST_PLAN.md` for the complete test plan to be executed when the device arrives.

---

## Key Design Decisions

1. **Model choice**: Qwen2-VL-2B-Instruct-MNN (INT4) is chosen because the 2B parameter count and INT4 quantization fit within the 6 GB runtime memory budget on 8 GB RAM devices. Larger models are deferred.

2. **MNN over other runtimes**: MNN is selected for its Android JNI support, low dependency footprint, and suitability for vision-language model deployment without requiring NNAPI or GPU delegation.

3. **Single APK, no root**: The deployment model is a standard user-space APK. Model weights are provisioned to `/sdcard/qwen_2b_mnn/` via ADB or in-app download; no system partition access is required.

4. **Schema-first parsing**: The inspection engine always emits structured JSON. Free-text output is rejected by the parser and yields `review_required`. This makes the safety behavior deterministic and independent of prompt drift.
