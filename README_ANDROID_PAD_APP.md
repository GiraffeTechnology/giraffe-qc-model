# GiraffeQC — Android Pad App Branch

> **Branch:** `android-pad-app`  
> **Separated from:** `main` (general giraffe-qc-model backend / shared QC model code)

## Purpose

This branch is the **Android Pad offline local-only QC application** branch.

It is intentionally separated from `main` to prevent mixing:

| `main` | `android-pad-app` |
|--------|------------------|
| Backend / cloud QC model code | Android Pad runtime only |
| Python QC service | Kotlin Android app |
| DashScope / Qwen API paths | **No cloud inference — forbidden** |
| Server deployment | On-device MNN inference |

## Product Rule

The Android Pad app on this branch:

- Is **offline-first**
- Is **local-only**
- Runs **on-device inference only**
- Uses **Qwen3-VL-4B-Instruct-MNN** via **MNN runtime only**
- **Never calls** Qwen API, DashScope, or any cloud inference endpoint
- Returns `review_required` whenever local MNN inference is not ready

## Quick Start

### Build

```bash
cd apps/android-qc
./gradlew :app:assemblePadLocalDebug
```

### Test

```bash
./gradlew :app:testPadLocalDebugUnitTest
```

### Check manifest — no INTERNET permission

```bash
./gradlew :app:processPadLocalDebugManifest
grep -R "android.permission.INTERNET" app/build/intermediates/merged_manifests/ || echo "PASS: No INTERNET permission"
```

### Sideload model to device

```bash
adb push ./Qwen3-VL-4B-Instruct-MNN/ /sdcard/qwen3_vl_4b_mnn/
```

### Offline pad test

```bash
adb shell svc wifi disable
adb shell svc data disable
./scripts/benchmark_mnn.sh -p /sdcard/qwen3_vl_4b_mnn -m "Qwen3-VL-4B-Instruct-MNN" -i 10 -o benchmark_qwen3_vl_4b_pad_local.json
```

## Required Model Files

All 10 files must be present at the sideload path:

```
llm.mnn
llm.mnn.weight
visual.mnn
visual.mnn.weight
llm.mnn.json
llm_config.json
embeddings_bf16.bin
tokenizer.txt
config.json
checksum.sha256
```

If any file is missing → result is `review_required`.

## Build Config Flags

| Flag | Value | Description |
|------|-------|-------------|
| `QWEN_MODEL_NAME` | `Qwen3-VL-4B-Instruct-MNN` | Model identifier |
| `PAD_LOCAL_ONLY` | `true` | Pad local-only mode |
| `QWEN_CLOUD_ENABLED` | `false` | Cloud inference disabled |
| `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN` | `false` | No image upload to cloud |
| `ALLOW_STUB_PASS` | `false` | No simulated pass results |

## Documentation

- [Android Pad Local-Only Architecture](docs/ANDROID_PAD_LOCAL_ONLY.md)
- [Pad MNN Deployment Guide](docs/PAD_LOCAL_MNN_DEPLOYMENT.md)
