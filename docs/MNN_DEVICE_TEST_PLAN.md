# MNN Device Test Plan

Test plan to be executed when the physical Snapdragon test device arrives. No phase in this document can be completed in a simulated environment.

---

## Prerequisites

| Requirement | Detail |
|-------------|--------|
| Device | Snapdragon 8 Gen, 8 GB RAM, 128 GB storage, Android 12+ |
| APK | Built from `apps/android-qc/` with `./gradlew :app:assemblePadLocalDebug` |
| Model | Qwen3-VL-4B-Instruct-MNN (INT4), provisioned per `PAD_LOCAL_MNN_DEPLOYMENT.md` |
| ADB | Connected with USB debugging enabled, `adb devices` shows device |
| Network | WiFi available for initial provisioning; must be disableable for offline tests |

All phases must be run in order. A failure in an earlier phase is a blocker for later phases — do not skip ahead.

---

## Phase 1: Model Provisioning

**Goal**: Confirm the Qwen3-VL-4B-Instruct-MNN (INT4) model weights are correctly placed on the device and recognized by the app.

**Steps**:

1. Push the model directory to the device:
   ```bash
   adb push <model_dir>/ /sdcard/qwen3_vl_4b_mnn/
   ```

2. Verify the checksum of the pushed files matches the expected value:
   ```bash
   adb shell "cd /sdcard/qwen3_vl_4b_mnn && sha256sum -c checksum.sha256"
   ```
   All files must report `OK`. Any mismatch is a blocker.

3. Launch the app and verify provisioning status via the debug diagnostics screen or logcat:
   ```
   ModelProvisioning.getStatus() == READY
   ```

**Pass criteria for Phase 1**:
- [ ] All checksum verifications pass
- [ ] `ModelProvisioning.getStatus()` returns `READY`

---

## Phase 2: Cold-Start Benchmark (§4.3.0)

**Goal**: Measure cold-start model load time and per-image inference latency against the defined hardware budgets.

**Steps**:

1. Run the benchmark script with 10 iterations:
   ```bash
   ./scripts/benchmark_mnn.sh -i 10
   ```

2. Record the following metrics:

   | Metric | Budget | Actual (record here) |
   |--------|--------|----------------------|
   | Cold-start load time | ≤ 30s | |
   | p50 per-image latency | — (record for baseline) | |
   | p95 per-image latency | ≤ 10s | |
   | Peak memory | ≤ 6 GB | |

**If p95 > 10s**:

Do not relax the budget. Report the measured numbers and select a mitigation from the following options:

| Mitigation | Trade-off |
|------------|----------|
| Switch to a smaller model variant | Reduced accuracy |
| Reduce input image resolution | May miss fine-grained defects |
| Narrow inspection scope (fewer QC points per call) | Multiple passes required per garment |

The budget is fixed; the implementation must adapt.

**Pass criteria for Phase 2**:
- [ ] Cold-start ≤ 30s
- [ ] p95 per-image latency ≤ 10s
- [ ] Peak memory ≤ 6 GB
- [ ] p50 baseline recorded

---

## Phase 3: JNI Integration

**Goal**: Replace the stub JNI implementation in `MnnQwenInspector.kt` with a real call to the native MNN inference library and confirm the Kotlin test suite passes.

**Steps**:

1. Open `MnnQwenInspector.kt` and replace the stub in `nativeRunInference()` with the real JNI call to the compiled MNN native library.

2. Wire `runtimeLoader.modelPtr` to the loaded model handle returned during provisioning.

3. Run the Kotlin unit tests:
   ```bash
   ./gradlew :app:testPadLocalDebugUnitTest
   ```

4. Confirm that `FakeOnDeviceQwenInspector` tests still pass — the fake inspector must not be broken by changes to the real inspector's wiring.

**Pass criteria for Phase 3**:
- [ ] `./gradlew :app:testPadLocalDebugUnitTest` exits with no failures
- [ ] All `FakeOnDeviceQwenInspector` tests pass
- [ ] Real `nativeRunInference()` is called (confirm via logcat, not stub log line)

---

## Phase 4: End-to-End APK Test (Offline)

**Goal**: Validate the full capture-to-result flow on the physical device with no network connectivity.

**Steps**:

1. Install the debug APK:
   ```bash
   adb install app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk
   ```

2. Disable WiFi and mobile data on the device.

3. Run the following inspection sequence in the app:
   - Capture a standard reference photo for a garment style
   - Define QC points for the inspection
   - Capture a production garment photo
   - Trigger inspection

4. Verify the following:

   | Check | Expected |
   |-------|----------|
   | On-device inspection completes | Yes |
   | Result displayed | `pass`, `fail`, or `review_required` |
   | No cloud call made while offline | Confirmed via network log / logcat |
   | Model not provisioned → result | `review_required` (not a crash) |

   For the "model not provisioned" check: temporarily rename the model directory on device, trigger an inspection, confirm `review_required` is returned, then restore the directory.

**Pass criteria for Phase 4**:
- [ ] Inspection completes offline
- [ ] Result displayed correctly
- [ ] Zero outbound network calls observed during offline inspection
- [ ] Unprovisioned model yields `review_required`, not a crash

---

## Phase 5: §4.5.4 Fail-is-Final on Device

**Goal**: Confirm that an on-device `fail` result cannot be promoted by any path.

**Steps**:

1. Capture or load a clearly defective garment image that reliably produces a `fail` from on-device inference.

2. Trigger inspection and observe:
   - On-device result is `fail`
   - Final result displayed is `fail`
   - No mechanism exists to promote `fail` to `pass` (cloud is disabled at compile time)

**Pass criteria for Phase 5**:
- [ ] On-device `fail` is returned
- [ ] Result remains `fail` with no override possible
- [ ] No mechanism exists to promote `fail` to `pass`

---

## Phase 6: Router Branch Validation (Device)

**Goal**: Exercise each non-happy-path branch of the inspection router on real hardware.

### Branch 1: Timeout

- Set `onDeviceTimeoutMs=100` in debug config (well below expected inference time)
- Trigger inspection
- Expected result: `review_required`

### Branch 2: Model Not Provisioned

- Move the model directory to a temporary location:
  ```bash
  adb shell mv /sdcard/qwen3_vl_4b_mnn /sdcard/qwen3_vl_4b_mnn_bak
  ```
- Trigger inspection
- Expected result: `review_required`
- Restore directory:
  ```bash
  adb shell mv /sdcard/qwen3_vl_4b_mnn_bak /sdcard/qwen3_vl_4b_mnn
  ```

### Branch 3: Low Confidence / Uncertain Result

- Capture an intentionally ambiguous or underexposed image
- Trigger inspection
- Expected result: `review_required` (cloud is disabled at compile time on Android Pad)

**Pass criteria for Phase 6**:
- [ ] Timeout → `review_required`
- [ ] Not provisioned → `review_required`
- [ ] Low confidence → `review_required` (no cloud path on Android Pad)

---

## Pass Criteria Summary

All of the following must be satisfied before the device test milestone is considered complete:

| Criterion | Status |
|-----------|--------|
| Cold-start ≤ 30s | [ ] |
| p95 per-image latency ≤ 10s | [ ] |
| Peak memory ≤ 6 GB | [ ] |
| All 6 phases complete with no failures | [ ] |
| On-device `fail` stays `fail` — §4.5.4 confirmed | [ ] |
| Offline inspection works (no network calls) | [ ] |
| 203+ existing Python tests still pass after JNI integration | [ ] |

The Python test suite must be re-run from the development environment after JNI integration changes are merged:

```bash
pytest tests/ -v
```

All 203+ tests must pass. A regression in the Python suite blocks the merge even if device tests pass.

---

## After Device Test

Once all pass criteria above are satisfied, update `README.md` as follows:

**In the Current State section**:

- Check off: "Real on-device MNN benchmark run"
- Check off: "Android app installed and validated on physical device"
- Record actual measured p50 and p95 latency numbers (replace placeholder values)

**Branch management**:

- Merge the device-test feature branch to `main`
- Tag the release commit with the benchmark results in the tag annotation

Do not merge to `main` if any pass criterion remains unchecked.
