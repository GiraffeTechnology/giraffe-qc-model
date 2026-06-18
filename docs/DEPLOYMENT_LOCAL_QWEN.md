# Deploying the Local QWEN Model (On-Device)

## Target Hardware

| Attribute       | Specification                        |
|-----------------|--------------------------------------|
| SoC             | Snapdragon 8 Gen                     |
| RAM             | 8 GB                                 |
| Storage         | 128 GB                               |
| OS              | Android 12+                          |
| Default model   | Qwen2-VL-2B-Instruct-MNN (INT4)      |

The 2B INT4 model requires approximately 3–4 GB at runtime. On an 8 GB device this leaves sufficient headroom for the OS and camera pipeline.

For devices with less than 4 GB available RAM, use Qwen2-VL-0.5B-Instruct-MNN instead.

## Model Source

**HuggingFace repository:** `taobao-mnn/Qwen2-VL-2B-Instruct-MNN`
`https://huggingface.co/taobao-mnn/Qwen2-VL-2B-Instruct-MNN`

Total size: ~4.3 GB. Last updated: 2025-05-07.

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

### Using huggingface-cli (recommended)

```bash
pip install huggingface_hub
huggingface-cli download taobao-mnn/Qwen2-VL-2B-Instruct-MNN \
    --local-dir ./qwen_2b_mnn
```

After download, generate the checksum file for `llm.mnn`:

```bash
cd qwen_2b_mnn
sha256sum llm.mnn | awk '{print $1}' > checksum.sha256
```

### Using git-lfs

```bash
git lfs install
git clone https://huggingface.co/taobao-mnn/Qwen2-VL-2B-Instruct-MNN qwen_2b_mnn
cd qwen_2b_mnn
sha256sum llm.mnn | awk '{print $1}' > checksum.sha256
```

## Provisioning Modes

### DOWNLOAD_ON_FIRST_RUN (default)

Configure via `ProvisioningConfig`. Note: this mode downloads `llm.mnn` only; the remaining
weight shards must be bundled in assets or sideloaded separately.

```kotlin
ProvisioningConfig(
    mode             = ProvisioningMode.DOWNLOAD_ON_FIRST_RUN,
    modelName        = "Qwen2-VL-2B-Instruct-MNN",
    modelDownloadUrl = "https://your-cdn.example.com/qwen_2b_mnn/llm.mnn",
    expectedSha256   = "<sha256_hex_of_llm_mnn>",
)
```

The app downloads on first launch, verifies the SHA-256, then stores the model locally. Subsequent launches skip the download.

### BUNDLED

For factory deployments where the model ships with the APK as an asset:

```kotlin
ProvisioningConfig(
    mode      = ProvisioningMode.BUNDLED,
    modelName = "Qwen2-VL-2B-Instruct-MNN",
)
```

Place all model files under `app/src/main/assets/models/qwen_mnn/` (including `checksum.sha256`).

## ADB Sideloading (Development / Benchmark)

Push the model directory to the device:

```bash
adb push ./qwen_2b_mnn/ /sdcard/qwen_2b_mnn/
```

Then launch via the BenchmarkActivity:

```bash
adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
    --es model_path /sdcard/qwen_2b_mnn \
    --ei iterations 10 \
    --es model_name "Qwen2-VL-2B-Instruct-MNN" \
    --ez cpu_only true
```

Or use the benchmark script (pass `-c` for CPU-only, `-a` to auto-install the APK):

```bash
./scripts/benchmark_mnn.sh \
    -d <device_serial> \
    -p /sdcard/qwen_2b_mnn \
    -i 10 \
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

Results are written to `/sdcard/qc_benchmark_results.json` and logcat tag `QCBenchmark`.

## Security Constraints

- The model file must pass SHA-256 verification before any inference call.
- Cloud credentials must never be embedded in the APK.
- Cloud fallback requires both `QWEN_CLOUD_ENABLED=true` and `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true`.
- On-device FAIL results are final and must not be overridden by cloud (§4.5.4).
