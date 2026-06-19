# Android Pad Local-Only Architecture

**Branch:** `android-pad-app`

> This branch is the Android Pad offline local-only application branch.
> It is separated from `main` to avoid mixing backend/cloud QC logic with the Pad runtime.
> The Pad app runs Qwen3-VL-4B-Instruct-MNN locally through MNN.
> The Pad app does **not** call Qwen API, DashScope, or any cloud inference endpoint.

## Architecture Overview

```
Android Pad (Snapdragon, 8+ GB RAM)
  │
  ├── MainActivity
  │     └── initInspectionPipeline()
  │
  ├── ModelProvisioning
  │     ├── SIDELOAD_FROM_SDCARD (default)
  │     │     └── searches /sdcard/qwen3_vl_4b_mnn
  │     │               /sdcard/Download/qwen3_vl_4b_mnn
  │     │               /sdcard/Android/data/.../import/qwen3_vl_4b_mnn
  │     └── BUNDLED (factory preload)
  │
  ├── MnnRuntimeLoader
  │     ├── loadNativeLibs() — System.loadLibrary("MNN", "MNN_Express")
  │     ├── isModelReady()  — validates all 10 required files
  │     └── loadModel()     — loads llm.mnn entry point
  │
  ├── MnnQwenInspector
  │     ├── inspect()       — calls nativeRunInference() [JNI, MNN AAR]
  │     └── if not ready    → returns review_required (never throws, never calls cloud)
  │
  └── QwenInspectionRouter
        ├── local pass (confidence >= 0.82)  → pass
        ├── local fail                       → fail (final)
        ├── local review_required            → review_required
        ├── model missing                    → review_required
        ├── MNN missing                      → review_required
        ├── inference not wired              → review_required
        ├── timeout                          → review_required
        └── cloud fallback                   → FORBIDDEN
```

## Safety Invariants

These invariants are enforced by code and verified by unit tests:

1. **No cloud call**: `QwenInspectionRouter` never calls `cloudInspector` regardless of config.
2. **No stub pass**: `ALLOW_STUB_PASS = false` is locked at compile time in `BuildConfig`.
3. **No simulated confidence**: Fake inspectors are only used in unit tests, never in production.
4. **Fail is final**: A local `fail` result is never escalated to cloud to produce `pass`.
5. **Partial model = not ready**: `isModelReady()` requires all 10 files. Missing 1 = `NOT_READY`.
6. **No internet**: `INTERNET` permission is absent from the main manifest and explicitly
   removed by the `padLocal` flavor manifest overlay.

## Router Policy

| Condition | Result |
|-----------|--------|
| local pass, confidence ≥ 0.82 | `pass` |
| local fail | `fail` (final) |
| local `review_required` | `review_required` |
| model missing | `review_required` |
| model incomplete | `review_required` |
| MNN libs missing | `review_required` |
| native inference not wired | `review_required` |
| JSON parse failure | `review_required` |
| timeout | `review_required` |
| cloud fallback | **FORBIDDEN** |
| Qwen API fallback | **FORBIDDEN** |

## Inference Output Schema

```json
{
  "overall_result": "pass | fail | review_required",
  "confidence": 0.0,
  "model_name": "Qwen3-VL-4B-Instruct-MNN",
  "summary": "",
  "items": [
    {
      "qc_point_id": "QC-01",
      "qc_point_code": "color_check",
      "name": "Color",
      "result": "pass | fail | review_required",
      "confidence": 0.0,
      "reason": ""
    }
  ],
  "fallback": {
    "used": false,
    "reason": null
  }
}
```

`enable_thinking` is set to `false` in the prompt.
The parser strips `<think>...</think>` blocks if present for forward compatibility.

## UI States

The `PadStatusScreen` composable shows these states:

| State | Display |
|-------|---------|
| Model not ready | `Local model not ready` (red) |
| Runtime not ready | `Local runtime not ready` (yellow) |
| Running | `Inspection running locally...` (teal) |
| Pass | `Result: PASS` (green) |
| Fail | `Result: FAIL` (red) |
| Review required | `Result: REVIEW REQUIRED` (yellow) |

Never shown:
- Qwen API key input
- DashScope key input
- Cloud fallback toggle
- Remote inference settings

Operator always sees:
```
Engine:  Local Qwen3-VL-4B MNN  ●
Mode:    Offline Pad             ●
Cloud:   Disabled                ·
Network: Not used                ·
```

## Manifest

- `INTERNET` permission: **absent** from `src/main/AndroidManifest.xml`
- `padLocal` flavor manifest (`src/padLocal/AndroidManifest.xml`) uses
  `tools:node="remove"` to explicitly strip `INTERNET` even if a library adds it.
- `READ_EXTERNAL_STORAGE` (maxSdkVersion 32): required only for sdcard model sideload.

## Model Files Required

```
llm.mnn            — LLM weights (MNN format)
llm.mnn.weight     — LLM weight shards
visual.mnn         — Vision encoder (MNN format)
visual.mnn.weight  — Vision encoder weight shards
llm.mnn.json       — LLM MNN graph config
llm_config.json    — LLM generation config
embeddings_bf16.bin — Token embeddings
tokenizer.txt      — Tokenizer vocab
config.json        — Model metadata
checksum.sha256    — SHA-256 checksum for llm.mnn
```

All 10 files must be present. A partial model is treated as `NOT_PROVISIONED`.
