# Xavier NX Administrator runner deployment runbook — Architecture v2

Status: **software implementation present; hardware deployment and validation
not run**. This replaces the Architecture v1 llama.cpp/Pad-to-Xavier runbook.
The Xavier is now used only for Administrator authoring, qualification, and
recheck. Operator Pad/Nano inference uses the cloud contract and must not fall
back to this service.

The runtime is provider-neutral. `qwen3-vl-4b` is the replaceable default
MNN-exported VLM, not the product identity or an ecosystem requirement.

## 1. Human preflight and reflash

1. Back up the device, record serial number, current image digest, installed
   packages, model digests, network configuration, and previous service logs.
2. Reflash the approved JetPack image from the approved x86 Ubuntu host using
   SDK Manager and Force Recovery. Retain the complete flash log. Do not
   simulate or mark this step complete from repository CI.
3. After boot, record JetPack/L4T, CUDA, cuDNN, TensorRT, disk, memory, and
   thermal baseline. Restore only reviewed configuration and credentials.

## 2. MNN bridge and model

1. Install the pinned Xavier-compatible MNN SDK and record its version/digest.
2. Install the configured exported VLM bundle and `model_manifest.json`. Record
   the actual model name, revision, file digests, and quantization.
3. Build the provider-neutral bridge:

   ```bash
   cmake -S jetson_runner/native -B build/xavier-mnn \
     -DMNN_ROOT=/opt/mnn-pinned
   cmake --build build/xavier-mnn --config Release
   ```

4. Install the resulting `libgiraffe_mnn_bridge.so` at the configured path.
   A successful build is not proof of model readiness or inference accuracy.

## 3. Service configuration

```bash
APP_ENV=production
XAVIER_INFERENCE_MODE=real
JETSON_DEVICE_ID=<stable provisioned id>
JETSON_BIND_HOST=<administrator LAN address>
JETSON_BIND_PORT=8600
XAVIER_MNN_BRIDGE_LIBRARY=/opt/giraffe/lib/libgiraffe_mnn_bridge.so
XAVIER_MNN_MODEL_DIR=/opt/giraffe/models/qwen3-vl-4b-mnn
XAVIER_MNN_MODEL_NAME=qwen3-vl-4b
XAVIER_ADMIN_CREDENTIALS_JSON=<provisioned bearer and Ed25519 public-key map>
XAVIER_HARDWARE_VALIDATION_STATUS=not_run
```

The model path/name above are defaults and may be replaced by a compatible MNN
VLM. TLS termination is required outside loopback. Install as a systemd unit
with least privilege and protected credential/environment files. Never set
mock mode in production; startup must refuse it.

## 4. Validation gate

Follow `jetson_runner/HARDWARE_VALIDATION.md`. At minimum retain:

- signed health before/after model load and after power-cycle;
- invalid token/signature, replay, digest mismatch, missing-model, timeout, and
  thermal/not-ready evidence;
- golden-image raw output, parsed point result, model revision, CV evidence,
  per-stage timing, memory, temperature, and throttling samples;
- five consecutive real workflow runs for each approved Administrator flow;
- service restart and full device power-cycle recovery evidence.

Only a reviewed immutable evidence record may set
`XAVIER_HARDWARE_VALIDATION_STATUS=passed` together with
`XAVIER_HARDWARE_VALIDATION_EVIDENCE_REF`. Repository CI, file existence, and
mock tests cannot satisfy this gate.

## 5. Current limitations

- WS8 OpenCV analyzer execution is wired through the shared deterministic
  package; health reports `cv_pipeline.status=ready` when that software package
  is loaded. This is not an accuracy or Xavier latency claim. Physical-device
  validation remains required by the hardware checklist.
- Idempotency and replay state are process-local. Durable encrypted persistence
  is required before cross-restart reconciliation can be claimed.
- Operator cloud integration, Pad health UI, and full product-loop evidence are
  separate WS4/WS3/integration deliverables.
