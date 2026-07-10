"""Headless mock Jetson Xavier NX qc-model inference runner.

Implements the Pad↔Jetson side of ``PRD_Pad_UI_CV_Jetson_QCModel_Inference.md``
and the headless-pairing P0 addendum, with **no display/keyboard/mouse** and no
Server dependency in the inference path:

* provisioning identity (device id + keypair + chassis fingerprint);
* headless pairing — USB (physical proof) and Wi-Fi (pairing-window + fingerprint);
* paired-identity signed-request auth (per-pair key, not a global secret),
  1:1, re-pair fail-closed with no grace;
* stateless-per-request qc-model inference (mock VLM) over the §4 contract;
* health/readiness reporting for the Pad (the only screen).

Mock mode needs no hardware, so CI exercises the whole flow. See README.
"""
