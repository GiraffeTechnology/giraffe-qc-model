# Deploying the Local QWEN Model (On-Device)

> **Android Pad branch**: This document describes the general on-device deployment
> architecture. For Android Pad-specific sideloading instructions (Qwen3-VL-4B-Instruct-MNN,
> approved sdcard paths, checksum verification), see
> [`docs/PAD_LOCAL_MNN_DEPLOYMENT.md`](PAD_LOCAL_MNN_DEPLOYMENT.md).

## Target Hardware

| Attribute       | Specification                               |
|-----------------|---------------------------------------------|
| SoC             | Snapdragon 8 Gen                            |
| RAM             | 8 GB                                        |
| Storage         | 128 GB                                      |
| OS              | Android 12+                                 |
| Default model   | Qwen3-VL-4B-Instruct-MNN (INT4)             |

The INT4-quantized model requires approximately 4–6 GB at runtime. On an 8 GB
device this leaves sufficient headroom for the OS and camera pipeline.

## Model Directory Structure

The app expects the model at `<app_files_dir>/models/qwen_mnn/`:

```
models/qwen_mnn/
  llm.mnn               ← INT4 quantized LLM weights
  llm.mnn.weight        ← external weight shard
  visual.mnn            ← visual encoder weights
  visual.mnn.weight     ← visual encoder weight shard
  llm.mnn.json          ← LLM graph config
  llm_config.json       ← model config
  embeddings_bf16.bin   ← embedding table
  tokenizer.txt         ← tokenizer vocab
  config.json           ← tokenizer config
  checksum.sha256       ← SHA-256 hex of llm.mnn (mandatory)
```

All 10 files are mandatory. The app will refuse to run inference if any file is
absent or if `checksum.sha256` does not match `llm.mnn`.

## Provisioning Modes

### SIDELOAD_FROM_SDCARD (Android Pad default)

Push the model directory to the device via ADB:

```bash
adb push path/to/local/Qwen3-VL-4B-Instruct-MNN/ /sdcard/qwen3_vl_4b_mnn/
```

The app searches these sdcard paths in order and imports to app-private storage:

```
/sdcard/qwen3_vl_4b_mnn
/sdcard/Download/qwen3_vl_4b_mnn
/sdcard/Android/data/com.giraffetechnology.qc/files/import/qwen3_vl_4b_mnn
```

See `docs/PAD_LOCAL_MNN_DEPLOYMENT.md` for the complete step-by-step guide.

### BUNDLED

For factory deployments where the model ships with the APK as an asset:

```kotlin
ProvisioningConfig(
    mode      = ProvisioningMode.BUNDLED,
    modelName = "Qwen3-VL-4B-Instruct-MNN",
)
```

Place all 10 model files under `app/src/main/assets/models/qwen_mnn/`
(including `checksum.sha256`). Checksum is always verified on first use.

## ADB Sideloading (Development / Benchmark)

Push the model directory to the device:

```bash
adb push path/to/local/Qwen3-VL-4B-Instruct-MNN/ /sdcard/qwen3_vl_4b_mnn/
```

Then launch via the BenchmarkActivity:

```bash
adb shell am start -n com.giraffetechnology.qc/.benchmark.BenchmarkActivity \
    --es model_path /sdcard/qwen3_vl_4b_mnn \
    --ei iterations 10 \
    --es model_name "Qwen3-VL-4B-Instruct-MNN"
```

Or use the benchmark script:

```bash
./scripts/benchmark_mnn.sh -p /sdcard/qwen3_vl_4b_mnn -i 10
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
- Checksum bypass is not permitted — a blank or absent `checksum.sha256` always
  returns `CHECKSUM_FAILED`, never `READY`.
- The INTERNET permission is not declared in the Android Pad manifest.
- On-device FAIL results are final and must not be overridden (§4.5.4).
