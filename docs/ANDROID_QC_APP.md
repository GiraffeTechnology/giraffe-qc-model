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

---

## Shared Sample Admin Page

The sample database and admin web UI at `/admin/samples` are **shared by the
Pad edition and the Server edition**. They are not Android-only.

The Pad connects to the factory LAN backend to search samples; the same
backend also serves the admin page for creating and managing those samples.
No admin code branches by edition.

See `docs/QC_SAMPLE_ADMIN_UI.md` for the full admin page documentation.

---

## Pad vs Server Edition

The system has two runtime editions. They share the sample DB, admin page,
and SKU API. They differ only in the Qwen model and inference permissions.

| Component | Pad Edition (`padLocal`) | Server Edition (`server`) |
|---|---|---|
| Sample DB | Shared | Shared |
| Sample Admin Page | Shared | Shared |
| SKU API | Shared | Shared |
| Standard Photos | Shared | Shared |
| Inspection Requirements | Shared | Shared |
| Detection Points | Shared | Shared |
| Qwen Model | Qwen3-VL-2B-Instruct-MNN | Qwen3-VL-8B |
| Qwen API | Disabled | Allowed if configured |
| Cloud Inference | Disabled | Allowed if configured |
| Version suffix | `*-padLocal` | `*-server` |

Edition is configured via the `QC_RUNTIME_EDITION` environment variable.
See `src/runtime/editions.py` for the full config module.

---

## SKU API Backend

The Android `ApiSkuRepository` calls the backend at:

```
GET /api/v1/sku/search?q={query}
GET /api/v1/sku/{sku_id}
```

As of this iteration, the backend implements both endpoints with a real database.
See `docs/QC_SAMPLE_DB_API.md` for the full schema and API reference.

### Search Response Shape

The backend returns exactly the shape `ApiSkuRepository` expects:

```json
{
  "items": [
    {
      "id": "sku-flower-001",
      "item_number": "ITEM-FLOWER-001",
      "name": "Artificial Flower A",
      "reference_image_url": "http://192.168.1.10:8080/assets/ref/sku-flower-001-front.jpg",
      "standard_photo_path": "/factory/ref/sku-flower-001-front.jpg"
    }
  ]
}
```

### Seeded SKUs

Three SKUs are available immediately after running the seed script:

| item_number | name |
|---|---|
| `ITEM-FLOWER-001` | Artificial Flower A |
| `ITEM-HAIRCLIP-001` | Hair Clip Standard |
| `ITEM-BRACELET-001` | Bracelet Standard |

Seed command:
```bash
uv run python scripts/seed_qc_sample_data.py
```

### Backend Connection

The Android Pad connects to the backend on the factory LAN.
Default backend URL (set in `PadRuntimeGraph`): `http://192.168.1.10:8080`

The backend does not require `tenant_id` from the Android client;
it defaults to `"default"` when the parameter is absent.

### Compatibility Status

| Android call | Backend status |
|---|---|
| `GET /api/v1/sku/search?q=...` | **Implemented** |
| `GET /api/v1/sku/{sku_id}` | **Implemented** |

The Android Pad UI can search real backend SKU data without any Android
code changes.
