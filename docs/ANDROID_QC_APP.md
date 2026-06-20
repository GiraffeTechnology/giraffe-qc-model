# Android QC App

## Overview

A single-APK Android application providing on-device visual quality control inspection using Qwen3-VL running via the MNN inference engine.

## Architecture

```
CameraX capture
    │
    ▼
LocalStorage (saves captures + standard photos locally first)
    │
    ▼
QwenInspectionRouter
    ├── MnnQwenInspector (on-device, primary)
    │       └── MNN JNI → Qwen3-VL-2B-Instruct-MNN (INT4)
    │
    └── CloudQwenInspector (fallback, requires explicit consent)
            └── DashScope API
    │
    ▼
QcResultParser (§4.3.5)
    │   ├── Strips markdown wrappers
    │   ├── Rejects hallucinated QC IDs
    │   ├── Fills missing items as review_required
    │   └── Clamps confidence to [0, 1]
    │
    ▼
InspectionResult (pass | fail | review_required)
```

## Module Layout

```
apps/android-qc/
  app/
    src/main/kotlin/com/giraffetechnology/qc/
      qwen/
        QwenInspector.kt          ← data types + interface
        QcPromptBuilder.kt        ← builds MNN inference prompt
        QcResultParser.kt         ← parses + validates model output
        QwenInspectionRouter.kt   ← on-device first routing + fallback
        MnnQwenInspector.kt       ← MNN JNI bridge (scaffold → production)
        MnnRuntimeLoader.kt       ← MNN native library loader
        ModelProvisioning.kt      ← download / bundle + SHA-256 verify
        fake/
          FakeInspectors.kt       ← deterministic fakes for CI tests
      benchmark/
        BenchmarkActivity.kt      ← §4.3.0 latency benchmark
      MainActivity.kt             ← entry point
    src/test/kotlin/...
      QcResultParserTest.kt
      QwenInspectorRouterTest.kt
      QcPromptBuilderTest.kt
      ModelProvisioningTest.kt
```

## Building

```bash
cd apps/android-qc
./gradlew assembleDebug
./gradlew test          # JVM unit tests (no device required)
```

## Running Unit Tests

```bash
./gradlew :app:test
```

All tests use fake inspectors and run without a device or real model.

## Deployment

See [DEPLOYMENT_LOCAL_QWEN.md](DEPLOYMENT_LOCAL_QWEN.md) for device requirements, model provisioning, and the ADB benchmark workflow.

## Safety Guarantees

- **Fail-closed**: parse errors and model timeouts return `review_required`, never `pass`.
- **§4.5.4**: an on-device `fail` result is final; cloud fallback cannot convert it to `pass`.
- **Dual-guard cloud**: both `cloudEnabled=true` and `allowSendImages=true` are required before any image leaves the device.
- **Checksum-mandatory**: model weights are SHA-256 verified on every provision; a mismatch halts the app.
