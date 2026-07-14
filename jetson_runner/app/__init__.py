"""Headless Xavier NX Administrator MNN recognition runner.

Architecture v2 uses this service for Administrator authoring, qualification,
and recheck workflows. It is not in the production Operator path. The runtime
is provider-neutral; Qwen is a replaceable deployment default.

* provisioning identity (device id + keypair + chassis fingerprint);
* headless pairing — USB (physical proof) and Wi-Fi (pairing-window + fingerprint);
* paired-identity signed-request auth (per-pair key, not a global secret),
  1:1, re-pair fail-closed with no grace;
* signed v2 Administrator recognition and reconciliation;
* persistent real MNN model-handle readiness;
* explicitly labeled, production-blocked test mock mode;
* truthful health and manual hardware-validation status.

CI exercises software seams only. It does not claim Xavier/MNN hardware
validation. See ``jetson_runner/README.md`` and ``HARDWARE_VALIDATION.md``.
"""
