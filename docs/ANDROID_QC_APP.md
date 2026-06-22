# Android QC App

## Overview

A single-APK Android application providing on-device visual quality control
inspection using **Qwen3-VL-2B-Instruct-MNN** running via the MNN inference
engine on an Android Pad.

Android Pad target model: **Qwen3-VL-2B-Instruct-MNN**.
Pad-side inference is local-only.

Current UI/backend integration supports SKU search, manual confirmation,
capture workflow, and safe MNN pending/review_required behavior.

Real JNI-backed native MNN inference remains a separate acceptance gate.

## Architecture

```
App launch
  → PadRuntimeGraph.init()
  → TaskSelectionScreen
      │  └ operator searches item number → ApiSkuRepository → factory LAN
      │  └ operator confirms SKU manually
  → QcCaptureScreen
      │  └ AutoCaptureController state machine
      │  └ manual or auto capture → still image only (NOT live frames)
  → PadInspectionCoordinator
      │  └ MNN not ready → MNN_PENDING / review_required
      │  └ MNN ready → MnnQwenInspector → local only
  → ResultScreen (shows ACCEPTED / NOT_ACCEPTED / review_required / MNN_PENDING)
```

## Network Rules

| Direction | Allowed |
|-----------|--------|
| Pad → factory LAN SKU API | Yes (SKU/task data only) |
| Pad → local Room / file storage | Yes |
| Pad → local MNN runtime | Yes |
| Pad → Qwen API / DashScope | **No** |
| Pad → cloud model fallback for QC | **No** |

## Module Layout

```
apps/android-qc/
  app/
    src/main/kotlin/com/giraffetechnology/qc/
      PadRuntimeGraph.kt           ← singleton production graph
      PadScreen.kt                 ← navigation state sealed class
      MainActivity.kt              ← entry point + navigation host
      ui/
        TaskSelectionScreen.kt     ← SKU search, manual confirm, photo match
        QcCaptureScreen.kt         ← 4:3 camera region + auto-capture state panel
        ResultScreen.kt            ← result display (ACCEPTED/review_required/MNN_PENDING)
      sku/
        ApiSkuRepository.kt        ← factory LAN SKU API with real JSON parsing
        BackendConnectionState.kt  ← Connected / Offline / Error
        TaskSelectionController.kt ← complete state machine
        PadInspectionCoordinator.kt← local inspection coordinator
        PadInspectionResult.kt     ← result data class (cloudInferenceUsed always false)
      qwen/
        MnnQwenInspector.kt        ← MNN JNI bridge (scaffold)
        MnnRuntimeLoader.kt        ← MNN native library loader
      capture/
        AutoCaptureController.kt   ← Idle→Searching→Locking→Locked→Captured state machine
        PendingTargetDetector.kt   ← safe placeholder (no fake result)
      camera/
        CameraUnavailableFrameSource.kt ← safe placeholder
```

## Building

```bash
bash scripts/download_mnn_android_libs.sh --ci-stubs
cd apps/android-qc
./gradlew clean
./gradlew :app:assemblePadLocalDebug --stacktrace
./gradlew :app:testPadLocalDebugUnitTest --stacktrace
```

## Safety Guarantees

- **Fail-closed**: parse errors and model timeouts return `review_required`, never `pass`.
- **No cloud QC inference**: `QWEN_CLOUD_ENABLED=false`, `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=false`.
- **No fake pass**: `ALLOW_STUB_PASS=false`.
- **MNN pending is explicit**: when MNN is unavailable the result is `MNN_PENDING` or
  `review_required`, never `ACCEPTED`.
- **User confirmation required**: all task confirmation paths require an explicit user tap;
  no auto-binding.

## MNN Status

Real JNI-backed `nativeRunInference()` is not yet wired. When MNN native libs are
absent the app displays `MNN_PENDING` / `review_required` instead of crashing or
returning a fake pass.

Do not claim production-ready offline QC inference until `nativeRunInference()` is
actually called and native logs confirm it.
