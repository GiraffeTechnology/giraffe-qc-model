# Pad Local MNN Deployment Guide

**Branch:** `android-pad-app`

> Deployment guide for Qwen3-VL-4B-Instruct-MNN on the Android Pad offline QC device.
> This guide covers sideload, factory preload, and build configuration.
> The Pad app does **not** connect to the internet for inference.

## Prerequisites

- Android Pad: Snapdragon SoC, 8+ GB RAM
- Android 8.0+ (minSdk 26)
- ADB installed on host machine
- Qwen3-VL-4B-Instruct-MNN model files (all 10 required)
- MNN-android.aar (obtain from MNN GitHub releases)

## Model File Checklist

Before deployment, verify all 10 files are present:

```bash
ls -lh ./Qwen3-VL-4B-Instruct-MNN/
# Expected:
# llm.mnn
# llm.mnn.weight
# visual.mnn
# visual.mnn.weight
# llm.mnn.json
# llm_config.json
# embeddings_bf16.bin
# tokenizer.txt
# config.json
# checksum.sha256
```

## Build Configuration

### 1. Add MNN AAR (when available)

```bash
cp MNN-android.aar apps/android-qc/app/libs/
```

Uncomment in `apps/android-qc/app/build.gradle.kts`:

```kotlin
compileOnly(files("libs/MNN-android.aar"))
```

Wire JNI in `MnnQwenInspector.kt`:

```kotlin
// Replace scaffold block:
val rawJson = nativeRunInference(
    runtimeLoader.modelPtr,
    buildImageInputJson(standardPhotos, capturedPhoto),
    prompt,
)
return QcResultParser.parse(rawJson, expectedIds, engineName)
```

### 2. Build the padLocal APK

```bash
cd apps/android-qc
./gradlew :app:assemblePadLocalDebug
```

APK output: `app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk`

### 3. Run Android unit tests

```bash
./gradlew :app:testPadLocalDebugUnitTest
```

### 4. Verify manifest — no INTERNET permission

```bash
./gradlew :app:processPadLocalDebugManifest
grep -R "android.permission.INTERNET" \
    app/build/intermediates/merged_manifests/ || echo "PASS: No INTERNET permission"
```

Expected: `PASS: No INTERNET permission`

## Sideload Deployment

### Step 1: Install APK

```bash
adb devices
adb install -r app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk
```

### Step 2: Push model files

Primary sideload path:

```bash
adb push ./Qwen3-VL-4B-Instruct-MNN/ /sdcard/qwen3_vl_4b_mnn/
```

Alternate paths (searched in order if primary not found):

```bash
# Alternate 1:
adb push ./Qwen3-VL-4B-Instruct-MNN/ /sdcard/Download/qwen3_vl_4b_mnn/

# Alternate 2:
adb push ./Qwen3-VL-4B-Instruct-MNN/ \
    /sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen3_vl_4b_mnn/
```

### Step 3: Verify model on device

```bash
adb shell ls /sdcard/qwen3_vl_4b_mnn/
# All 10 files must be listed
```

### Step 4: Disable network (offline test)

```bash
adb shell svc wifi disable
adb shell svc data disable
```

### Step 5: Run benchmark

```bash
./scripts/benchmark_mnn.sh \
  -p /sdcard/qwen3_vl_4b_mnn \
  -m "Qwen3-VL-4B-Instruct-MNN" \
  -i 10 \
  -o benchmark_qwen3_vl_4b_pad_local.json
```

### Step 6: Verify no cloud calls in logs

```bash
adb logcat -d | grep -Ei "Qwen|DashScope|http|https|cloud|fallback|MNN|QCBenchmark"
# Expected: Only local MNN log lines. No http/https, no DashScope, no cloud fallback.
```

## Factory Preload

For factory-preloaded devices, embed model files in `app/src/main/assets/models/qwen_mnn/`
and set provisioning mode in `ProvisioningConfig`:

```kotlin
ProvisioningConfig(
    mode      = ProvisioningMode.BUNDLED,
    modelName = "Qwen3-VL-4B-Instruct-MNN",
)
```

The `provisionFromAssets()` method copies all 10 required files from assets to
`filesDir/models/qwen_mnn` on first launch.

## Model Provisioning Flow

```
App start
  │
  ├── ModelProvisioning.getStatus()
  │     ├── READY              → load MNN runtime → inspect
  │     ├── NOT_PROVISIONED    → show "model not ready" → review_required
  │     ├── PARTIAL_MODEL      → show "model not ready" → review_required
  │     └── CHECKSUM_FAILED    → show "model not ready" → review_required
  │
  └── ModelProvisioning.provision()
        ├── SIDELOAD_FROM_SDCARD: importFromSdcard()
        │     1. Search /sdcard/qwen3_vl_4b_mnn (primary)
        │     2. Search /sdcard/Download/qwen3_vl_4b_mnn
        │     3. Search /sdcard/Android/data/.../import/qwen3_vl_4b_mnn
        │     4. Copy all REQUIRED_MODEL_FILES to filesDir/models/qwen_mnn
        │     5. Verify isModelReady() after copy
        └── BUNDLED: provisionFromAssets()
              1. Copy from assets/models/qwen_mnn/
              2. Verify all 10 files present
              3. Verify checksum if expectedSha256 is set
```

## Static Scan Commands

Run from repo root on the `android-pad-app` branch:

```bash
# 1. Confirm branch
git branch --show-current
# Expected: android-pad-app

# 2. Old model cleanup
git grep -nE "Qwen2|Qwen2\.5|Qwen2-VL-2B|qwen_2b_mnn|FakeQwen-2B" \
    -- README.md docs scripts apps/android-qc || true
# Expected: No matches

# 3. Cloud/API cleanup
git grep -nE "DashScope|DASHSCOPE|QWEN_API_KEY|Qwen API|OpenAI-compatible|ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true|QWEN_CLOUD_ENABLED=true|cloudEnabled = true|okhttp" \
    -- apps/android-qc docs/ANDROID_PAD_LOCAL_ONLY.md docs/PAD_LOCAL_MNN_DEPLOYMENT.md || true
# Expected: No active cloud inference paths

# 4. Stub pass cleanup
git grep -nE "STUB_MODE.*pass|simulated pass|confidence = 0\.94|fake pass" \
    -- apps/android-qc || true
# Expected: No matches

# 5. INTERNET permission check (after processPadLocalDebugManifest)
cd apps/android-qc
./gradlew :app:processPadLocalDebugManifest
grep -R "android.permission.INTERNET" \
    app/build/intermediates/merged_manifests/ || echo "PASS: No INTERNET permission"
```

## MNN Runtime Status

| Status | Meaning | Inspection Result |
|--------|---------|------------------|
| MNN AAR not present | Native libs absent | `review_required` |
| MNN AAR present, model incomplete | Model files missing | `review_required` |
| MNN AAR present, model complete, JNI not wired | Scaffold mode | `review_required` |
| MNN AAR present, model complete, JNI wired | **Production mode** | `pass / fail / review_required` |

Current branch status: **Scaffold mode** (MNN AAR JNI not yet wired).
All inspections return `review_required` until `nativeRunInference()` is wired.
