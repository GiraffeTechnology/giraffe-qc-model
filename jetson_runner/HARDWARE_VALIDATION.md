# Xavier MNN hardware validation

Status: **not run**. This repository and CI do not contain an Xavier NX, the
pinned MNN SDK, or the exported VLM weights. The adapter is a real fail-closed
runtime path, but its presence is not evidence of successful hardware inference.

The configured model is provider-neutral. `qwen3-vl-4b` is the deployment
default, not a required product identity; record the actual configured model
and revision in every validation result.

## Manual procedure

1. Reflash the Xavier NX with the approved JetPack image and retain the flash
   log, image digest, device serial, and operator identity.
2. Install the pinned MNN SDK and exported VLM bundle. Record MNN version,
   model name, model revision/digests, quantization, and all build flags.
3. Build `native/` with `MNN_ROOT` pointing to that SDK. Install
   `libgiraffe_mnn_bridge.so` at the configured path.
4. Configure administrator credentials, `XAVIER_INFERENCE_MODE=real`, the
   bridge path, model directory, and model name. Confirm mock mode refuses to
   start under `APP_ENV=production`.
5. Start the service and verify signed health reports `model_loaded=true` only
   after the native handle has loaded. Test invalid signature, replay, digest
   mismatch, missing model, and thermal/not-ready paths.
6. Run the approved golden-image set through each administrator workflow.
   Retain raw model output, parsed result, CV evidence, per-stage timing,
   temperature/throttling samples, and process logs.
7. Power-cycle and repeat readiness plus one golden request. Confirm no monitor,
   interactive login, or mock fallback is needed.

Only after the evidence is reviewed may deployment configuration change
`hardware_validation.status` from `not_run` and supply an immutable evidence
reference. Do not infer that status from file existence or a successful CI run.
