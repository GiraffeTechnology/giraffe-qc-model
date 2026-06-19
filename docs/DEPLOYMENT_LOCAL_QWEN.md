# Deploying the Local QWEN Model (On-Device)

## Target Hardware

| Attribute       | Specification                           |
|-----------------|-----------------------------------------|
| SoC             | Snapdragon 8 Gen                        |
| RAM             | 8 GB                                    |
| Storage         | 128 GB                                  |
| OS              | Android 12+                             |
| Default model   | Qwen3-VL-4B-Instruct-MNN (INT4)         |

The INT4-quantized 4B model is viable on 8 GB devices. Runtime memory usage is pending physical-device measurement; see `MNN_DEVICE_TEST_PLAN.md` for the benchmark plan.

## Model Source

**ModelScope repository:** `MNN/Qwen3-VL-4B-Instruct-MNN`

## Model Directory Structure

The app expects the model at `<app_files_dir>/models/qwen_mnn/`:

```
models/qwen_mnn/
  llm.mnn              ← INT4 quantized LLM weights
  llm.mnn.weight       ← LLM weight shard
  visual.mnn           ← Vision encoder graph
  visual.mnn.weight    ← Vision encoder weight shard
  llm.mnn.json         ← LLM graph metadata
  llm_config.json      ← Model configuration
  embeddings_bf16.bin  ← Token embeddings
  tokenizer.txt        ← Tokenizer vocabulary
  config.json          ← Tokenizer config
  checksum.sha256      ← SHA-256 hex of llm.mnn (mandatory)
```

The checksum file is mandatory. The app will refuse to run inference if it is absent or if the checksum mismatches.

## Downloading the Model

### Using modelscope (recommended)

```bash
pip install modelscope
modelscope download MNN/Qwen3-VL-4B-Instruct-MNN --local_dir ./Qwen3-VL-4B-Instruct-MNN
```

After download, generate the checksum file for `llm.mnn`:

```bash
cd Qwen3-VL-4B-Instruct-MNN
sha256sum llm.mnn | awk '{print $1}' > checksum.sha256
```

### Using git-lfs

```bash
git lfs install
git clone https://modelscope.cn/MNN/Qwen3-VL-4B-Instruct-MNN.git Qwen3-VL-4B-Instruct-MNN
cd Qwen3-VL-4B-Instruct-MNN
sha256sum llm.mnn | awk '{print $1}' > checksum.sha256
```

## Provisioning Modes

### DOWNLOAD_ON_FIRST_RUN (default)

Configure via `ProvisioningConfig`. Note: this mode downloads `llm.mnn` only; the remaining
weight shards must be bundled in assets or sideloaded separately.

```kotlin
ProvisioningConfig(
    mode             = ProvisioningMode.DOWNLOAD_ON_FIRST_RUN,
    modelName        = "Qwen3-VL-4B-Instruct-MNN",
    modelDownloadUrl = "https://your-cdn.example.com/qwen3_vl_4b_mnn/llm.mnn",
    expectedSha256   = "<sha256_hex_of_llm_mnn>",
)
```

The app downloads on first launch, verifies the SHA-256, then stores the model locally. Subsequent launches skip the download.

### BUNDLED

For factory deployments where the model ships with the APK as an asset:

```kotlin
ProvisioningConfig(
    mode      = ProvisioningMode.BUNDLED,
    modelName = "Qwen3-VL-4B-Instruct-MNN",
)
```

Place all model files under `app/src/main/assets/models/qwen_mnn/` (including `checksum.sha256`).

## ADB Sideloading (Development / Benchmark)

The app uses `getExternalFilesDir()` for both model loading and results output —
no `MANAGE_EXTERNAL_STORAGE` permission is required on Android 10+ / Android 16
scoped storage. ADB can push to the app's scoped external directory without root.

Push the model directory to the device:

```bash
adb push ./Qwen3-VL-4B-Instruct-MNN/ /sdcard/qwen3_vl_4b_mnn/
```

Then launch via the BenchmarkActivity (pass `--es model_path` so the app knows
where to look on this device):

```bash
adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
    --ei iterations 10 \
    --es model_name "Qwen3-VL-4B-Instruct-MNN" \
    --es model_path /sdcard/qwen3_vl_4b_mnn \
    --ez cpu_only true
```

Results are written to:
`/sdcard/Android/data/com.giraffetechnology.qc/files/qc_benchmark_results.json`

Or use the benchmark script (pass `-c` for CPU-only, `-a` to auto-install the APK):

```bash
./scripts/benchmark_mnn.sh \
    -d <device_serial> \
    -i 10 \
    -p /sdcard/qwen3_vl_4b_mnn \
    -a apps/android-qc/app/build/outputs/apk/debug/app-debug.apk \
    -c
```

Build the debug APK first (requires Android Studio / JDK on the host machine):

```bash
cd apps/android-qc
./gradlew assembleDebug
# APK output: app/build/outputs/apk/debug/app-debug.apk
```

## Performance Budgets (§4.3.0)

| Metric            | Budget          |
|-------------------|-----------------|
| Cold-start load   | ≤ 30 s          |
| p95 per-image     | ≤ 10 s          |
| Peak memory       | ≤ 6 GB          |

Actual measurements pending physical-device benchmark run. See `MNN_DEVICE_TEST_PLAN.md`.

Results are written to `/sdcard/qc_benchmark_results.json` and logcat tag `QCBenchmark`.

## Security Constraints

- The model file must pass SHA-256 verification before any inference call.
- Cloud credentials must never be embedded in the APK.
- Cloud fallback requires both `QWEN_CLOUD_ENABLED=true` and `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true`.
- On-device FAIL results are final and must not be overridden by cloud (§4.5.4).
