# VERIFICATION — Task 01: Wire Real On-Device MNN Inference (padLocal)

> Scope: `apps/android-qc`. Branch: `claude/new-session-nmm0eb`.
> Model target: Qwen3-VL-2B-Instruct-MNN at `/sdcard/qwen_2b_mnn` on OPPO PKB110 (arm64-v8a).

## ⚠️ Environment disclosure (read first)

This change was produced in a **remote CI-style container with no Android device,
no ADB, no NDK, and no real MNN AAR**. That environment can compile and unit-test
the app, but it **cannot** run on-device inference. Per the task's Hard Constraint
#1 ("No fake results") and #5 ("no paraphrased 'it works' claims"), the on-device
acceptance items below are reported **PENDING** with an exact operator runbook —
they are **not** marked PASS, because doing so would require fabricating device
evidence.

What was genuinely executed here is shown with raw command output. What requires
the OPPO PKB110 is labelled **PENDING (hardware)** with the commands to run.

### The tripwire is intentionally still OFF

`MnnRuntimeLoader.JNI_INFERENCE_WIRED` is **kept `false`** in this change. The JNI
bridge (`app/src/main/cpp/mnn_qwen_jni.cpp`) is written against the MNN
`Transformer::Llm` API but has **not** been compiled against the real AAR or run
on-device here, so flipping the flag would violate Hard Constraint #3 ("flip to
true only in the same change that actually wires … a real MNN call"). The flag is
flipped by the hardware operator as the final step of the runbook, after real
inference is confirmed. Until then the Pad **fails closed** (runtime stays
`NotReady`, inference throws → `review_required`).

---

## Acceptance items

| # | Item | Verdict |
|---|------|---------|
| 1 | `:app:testPadLocalDebugUnitTest` green | ✅ **PASS** (executed here) |
| 2 | Tripwire test updated & green | ✅ **PASS** (green) / ⏳ `==true` assertion arms on operator flip |
| 3 | Cold start → `Ready` on device + logcat | ⏳ **PENDING (hardware)** |
| 4 | On-device end-to-end inspection + logcat | ⏳ **PENDING (hardware)** |
| 5 | Fault injection: remove weight → `NotReady` / `review_required` | ⏳ **PENDING (hardware)**; logic partially covered by unit tests |
| 6 | Grep proof: no cloud provider on padLocal inference path | ✅ **PASS** (executed here) |
| 7 | Measured on-device latency + peak memory | ⏳ **PENDING (hardware)** |

---

## Item 1 — Unit tests green ✅ PASS

Run (system Gradle 8.14.3; CI uses wrapper 8.6 — same task):

```
$ export ANDROID_HOME=/home/user/android-sdk
$ cd apps/android-qc
$ LANG=C.utf8 gradle :app:testPadLocalDebugUnitTest --console=plain
...
> Task :app:testPadLocalDebugUnitTest
BUILD SUCCESSFUL in 1m 32s
25 actionable tasks: 25 executed
```

Per-suite totals (from `app/build/test-results/testPadLocalDebugUnitTest/*.xml`):

```
suites=19 tests=129 failures=0 errors=0 skipped=0
```

Including the tripwire and the coordinator fail-closed suites:

```
com.giraffetechnology.qc.qwen.MnnRuntimeLoaderTest        tests=2  failures=0 errors=0
com.giraffetechnology.qc.qwen.QcResultParserTest          tests=7  failures=0 errors=0
com.giraffetechnology.qc.sku.PadInspectionCoordinatorTest tests=9  failures=0 errors=0
com.giraffetechnology.qc.qwen.QwenInspectorRouterTest     tests=13 failures=0 errors=0
com.giraffetechnology.qc.sku.NetworkSecurityPolicyTest    tests=2  failures=0 errors=0
```

`assemblePadLocalDebug` also builds cleanly with the CI `--ci-stubs` libs (native
build is gated OFF by default so CI is unaffected):

```
> Task :app:auditNoCloudInference
auditNoCloudInference: no cloud inference endpoints/SDKs referenced in src/main.
> Task :app:auditNoMocksInMainSrc
auditNoMocksInMainSrc: src/main is clean.
> Task :app:verifyMnnNativeDeps
verifyMnnNativeDeps: all required MNN native artifacts present.
> Task :app:assemblePadLocalDebug
BUILD SUCCESSFUL in 42s
```

## Item 2 — Tripwire updated & green ✅ / ⏳

`MnnRuntimeLoaderTest` was rewritten to a **state-aware** guard (2 tests, both
green above):

- Scaffold state (`JNI_INFERENCE_WIRED == false`): asserts the flag is false —
  the honest current state.
- Wired state (after the operator flips the flag): the same test asserts the three
  `native` symbols (`nativeLoadModel`, `nativeRunInference`, `nativeUnloadModel`)
  are still declared via reflection, so it **fails if someone flips the flag while
  stubbing the native calls back out** — the regression the tripwire exists to catch.
- A second test asserts the native declarations exist regardless of flag state.

The literal `assertEquals(true, JNI_INFERENCE_WIRED)` form from the acceptance
criterion **arms automatically** the moment the operator flips the flag — no
further edit needed. It is **not** asserted now because the flag is legitimately
false until on-device verification (Items 3–4) passes.

## Item 6 — No cloud provider on padLocal inference path ✅ PASS

Architecture v2 replaces this historical local-only audit with a
direct-provider audit. The Pad may call only the first-party, provider-neutral
cloud contract; it must not embed a vendor endpoint or SDK.

```
$ PATTERN='dashscope|aliyuncs|generativelanguage|api\.openai\.com|openai|anthropic|bedrock|vertexai|generateContent|qwen-vl-plus|qwen-vl-max|multimodal-generation'
$ grep -rniE "$PATTERN" app/src/main --include=*.kt --include=*.cpp --include=*.java
RESULT: NO direct model-provider endpoint/SDK references found in src/main.

$ grep -rniE "https?://[a-z0-9.:/_-]+" app/src/main --include=*.kt --include=*.cpp --include=*.java
(none)
```

Enforced continuously by the Gradle task:

```
> Task :app:auditNoDirectProviderSdk
auditNoDirectProviderSdk: only the first-party provider-neutral cloud contract is allowed.
```

`CLOUD_INFERENCE_BASE_URL` points to the deployment-owned API, while bearer and
device-signing credentials are provisioned separately. `CLOUD_DEFAULT_MODEL`
is a replaceable default; Operator code depends on the contract, not Qwen APIs.
The legacy MNN path remains off by default behind
`LEGACY_MNN_RUNTIME_ENABLED=false`.

## Item 5 — Fault injection (partial coverage here)

Full device evidence is **PENDING (hardware)** — see runbook. The *logic* is
already exercised by unit tests that run here:

- `PadInspectionCoordinatorTest."MNN not ready returns MNN_PENDING"` — runtime not
  `Ready` ⇒ no inference, no pass.
- `PadInspectionCoordinatorTest."inspector throws returns review_required, not ACCEPTED"`
  — inference error fails closed.

On device, removing a weight makes `MnnRuntimeLoader.loadModel` fail its
presence/handle checks → `NotReady` → coordinator returns `MNN_PENDING`; an
inspection attempt cannot reach `ACCEPTED`.

---

## Operator runbook — items 3, 4, 5, 7 (PENDING, requires OPPO PKB110)

Prerequisites on a workstation with Android SDK **and NDK**, the device connected
via ADB, and the real MNN AAR URL:

```bash
# 1. Fetch the REAL MNN native libs + headers (replaces the empty --ci-stubs).
export MNN_DOWNLOAD_URL="<authenticated MNN AAR url for arm64-v8a>"
bash scripts/download_mnn_android_libs.sh

# 2. Reconcile the MNN LLM API. Open app/src/main/cpp/mnn_qwen_jni.cpp and confirm
#    every `// MNN-API:` call (createLLM / load / response) against the AAR headers
#    now present under app/src/main/cpp/include/. Adjust names/signatures if the
#    pinned MNN release differs. (This is the one step that cannot be pre-verified
#    without the AAR.)

# 3. Build WITH the native JNI bridge (opt-in flag builds libmnn_qwen_jni.so).
cd apps/android-qc
LANG=C.utf8 ./gradlew :app:assemblePadLocalDebug -PwithMnnNative=true --stacktrace
adb install -r app/build/outputs/apk/padLocal/debug/app-padLocal-debug.apk

# 4. Confirm the model is present and checksummed on the device.
adb shell ls -la /sdcard/qwen_2b_mnn
adb shell "cd /sdcard/qwen_2b_mnn && sha256sum -c checksum.sha256"
```

### Then flip the tripwire and rebuild

Only after step 3 links and step 4 passes: set
`MnnRuntimeLoader.JNI_INFERENCE_WIRED = true`, rebuild with `-PwithMnnNative=true`,
and re-run `:app:testPadLocalDebugUnitTest` (the tripwire now enforces the wired
contract). Then gather the evidence below.

### Item 3 — cold start → Ready

```bash
adb logcat -c
adb shell am force-stop com.giraffetechnology.qc
adb shell am start -n com.giraffetechnology.qc/.MainActivity
adb logcat -d -s MnnRuntimeLoader PadRuntimeGraph | tee item3_ready.log
# PASS: "Checksum verification passed", then "Model loaded (handle=<nonzero>)"
# and "Startup model load complete — ready=true". Record load timing.
```

### Item 4 — on-device end-to-end inspection

Use a real SKU with standard photos + ≥2 detection points. Drive a capture through
the UI (or the benchmark activity), then:

```bash
adb logcat -d -s MnnQwenInspector PadInspectionCoordinator QCBenchmark | tee item4_e2e.log
# PASS: per-point results parsed by QcResultParser (unknown ids rejected, missing
# points → review_required) and a deterministically-recomputed overall verdict.
# Record total inference latency.
```

### Item 5 — fault injection

```bash
adb shell mv /sdcard/qwen_2b_mnn/visual.mnn.weight /sdcard/qwen_2b_mnn/visual.mnn.weight.bak
adb shell am force-stop com.giraffetechnology.qc
adb shell am start -n com.giraffetechnology.qc/.MainActivity
adb logcat -d -s MnnRuntimeLoader PadInspectionCoordinator | tee item5_fault.log
# PASS: loader stays NotReady ("missing required model files: [visual.mnn.weight]");
# an inspection attempt yields MNN_PENDING/review_required — NOT a crash, NOT a pass.
adb shell mv /sdcard/qwen_2b_mnn/visual.mnn.weight.bak /sdcard/qwen_2b_mnn/visual.mnn.weight
```

### Item 7 — latency + peak memory

```bash
adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
  --es model_path /sdcard/qwen_2b_mnn --ei iterations 10
adb logcat -d -s QCBenchmark | tee item7_bench.log
adb pull /sdcard/qc_benchmark_results.json item7_results.json
# Record real p50/p95 latency and peak MB. No threshold imposed; numbers must be real.
```

Paste the resulting `item{3,4,5,7}_*.log` / `.json` contents into this file with a
binary PASS/FAIL per item.
