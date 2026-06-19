# V3 On-Device QWEN QC Product Architecture

## Product Goal

Deliver a single Android APK for apparel and textile quality control (QC) inspection that:

- Installs on a standard Android device with no root and no separate server
- Uses **Qwen3-VL-4B-Instruct-MNN** running on-device via the **MNN inference framework** as the primary inspection engine
- Operates fully offline — no cloud connectivity required or used on Android Pad
- Meets the latency and memory budget of Snapdragon 8 Gen class hardware

The target hardware profile is:

| Parameter | Value |
|-----------|-------|
| SoC | Snapdragon 8 Gen |
| RAM | 8 GB |
| Storage | 128 GB |
| Model | Qwen3-VL-4B-Instruct-MNN (INT4) |
| Estimated runtime memory | ~4–6 GB |

The INT4-quantized 4B model is targeted for this hardware. Larger models or FP16 weights are out of scope for this branch.

---

## Engine Modes

The system is configured via the `QC_ENGINE_MODE` environment variable. Three modes are defined:

### 1. `cloud_qwen_dev` (temporary, Python backend only)

- Routes all inspection requests to the cloud Qwen API (Python backend)
- Used for backend development and validation before the physical Android test device arrives
- Not applicable to the Android Pad build; the Pad build has no cloud path
- Allows iterating on schema, parser, and prompt logic without hardware

### 2. `on_device_first` (Android Pad architecture)

- On-device MNN inference is the **primary and only engine** on Android Pad
- No cloud path is available or configured
- Offline inspection is fully supported
- This is the Android Pad shipping architecture

### 3. `backend_proxy` (specific use cases only)

- Cloud Qwen is the primary engine
- On-device MNN is not used
- Reserved for use cases where network connectivity is guaranteed and on-device latency budget cannot be met (e.g., bulk audit workstations)
- Not applicable to the Android Pad build

---

## Inspection Flow

```
Capture image
     │
     ▼
Standard photo + QC point config loaded
     │
     ▼
On-device MNN inference (Qwen3-VL-4B-Instruct-MNN)
     │
     ▼
Parser validates strict JSON schema
     │
     ├─ schema valid ──────────────────────────────────────┐
     │                                                     │
     └─ schema invalid / uncertain                         │
              │                                            │
              ▼                                            ▼
     review_required                        Result display (pass / fail /
     (no cloud path on Android Pad)         review_required)
                                                   │
                                                   ▼
                                        Optional backend sync
                                        (audit / fleet reporting)
```

Steps in detail:

1. **Capture** — camera captures the production garment image
2. **QC point config** — standard reference photo and per-point inspection criteria are loaded
3. **On-device inference** — MnnQwenInspector runs Qwen3-VL-4B-Instruct-MNN via MNN JNI
4. **Parser** — output is validated against the strict JSON schema; malformed output is rejected
5. **Result display** — one of `pass`, `fail`, or `review_required` is shown to the operator
6. **Backend sync** (optional) — result, metadata, and audit trail pushed to backend when connectivity is available

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
| Confidence below threshold | `review_required` (no cloud path on Android Pad) |

`review_required` always routes the item to a human inspector. It never becomes an automatic pass.

### §4.5.4: `on_device_fail_is_final=true`

When the on-device engine returns `fail`, that result is **final**:

- No override path exists on Android Pad
- The backend **cannot override** a device `fail` to `pass`
- This rule exists to prevent a misconfigured or compromised endpoint from clearing defective items

---

## Privacy Policy

### Local-Only Default

All inference runs on-device. On Android Pad, no image data leaves the device under any condition — INTERNET permission is not declared in the manifest.

### Compile-Time Guards on Android Pad

The following BuildConfig fields are locked at compile time in the `padLocal` product flavor:

| Guard | Value | Purpose |
|-------|-------|---------|
| `PAD_LOCAL_ONLY` | `true` | Identifies Pad local-only build |
| `QWEN_CLOUD_ENABLED` | `false` | Disables cloud API connectivity |
| `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN` | `false` | Prevents image data leaving device |
| `ALLOW_STUB_PASS` | `false` | Prevents stub from returning pass |

### `contains_pii` Flag

Assets in the abcdYi/Giraffe CAP asset registry carry a `contains_pii` boolean flag. Assets with `contains_pii=true` are never eligible for cloud transmission, independent of any other setting.

---

## Backend Role

The backend is **not** the primary inspection engine. Its responsibilities are limited to:

| Role | Description |
|------|-------------|
| Audit trail | Stores inspection outcomes with timestamps and device ID |
| Fleet reporting | Aggregates pass/fail/review_required rates across devices |
| CAP asset registry | Manages abcdYi/Giraffe standard reference photos and QC point configs |
| Backend aggregation | Receives completed inspection results from devices |

The backend does not make primary pass/fail decisions. It receives results that the device has already determined.

---

## Implementation Status

### Implemented (Simulated Environment)

The following components are implemented and tested in the simulated/CI environment without requiring a physical device:

| Component | Status |
|-----------|--------|
| Strict JSON output schema | Implemented |
| Schema parser and validator | Implemented |
| Inspection router (`on_device_first` / local-only for Pad) | Implemented |
| FakeOnDeviceQwenInspector (stub for unit tests) | Implemented |
| FastAPI backend endpoints (inspection, audit, fleet, asset registry) | Implemented |
| Android skeleton (MnnQwenInspector.kt with stub JNI) | Implemented |
| §4.5.4 fail-is-final logic (router level) | Implemented |
| Compile-time privacy guards (padLocal BuildConfig) | Implemented |
| Python unit/integration test suite (203+ tests) | Implemented |

### Requires Physical Android Test Device

The following cannot be validated without hardware:

| Component | Blocker |
|-----------|--------|
| Real MnnQwenInspector JNI (`nativeRunInference()`) | Requires MNN native libs on target ABI |
| Cold-start load time (budget: ≤30s) | Requires Snapdragon hardware |
| p50 / p95 per-image latency (budget: ≤10s p95) | Requires Snapdragon hardware |
| Peak memory measurement (budget: ≤6 GB) | Requires Android profiler on device |
| Full capture → result APK install and run | Requires physical device |
| Offline mode validation (no network calls) | Requires device with WiFi disabled |

See `MNN_DEVICE_TEST_PLAN.md` for the complete test plan to be executed when the device arrives.

---

## Key Design Decisions

1. **Model choice**: Qwen3-VL-4B-Instruct-MNN (INT4) is chosen as the target model for the Android Pad build. INT4 quantization fits within the 6 GB runtime memory budget on 8 GB RAM devices.

2. **MNN over other runtimes**: MNN is selected for its Android JNI support, low dependency footprint, and suitability for vision-language model deployment without requiring NNAPI or GPU delegation.

3. **Single APK, no root**: The deployment model is a standard user-space APK. Model weights are provisioned to `/sdcard/qwen3_vl_4b_mnn/` via ADB sideload; no system partition access is required.

4. **Schema-first parsing**: The inspection engine always emits structured JSON. Free-text output is rejected by the parser and yields `review_required`. This makes the safety behavior deterministic and independent of prompt drift.
