"""Jetson Xavier NX qc-model inference runner integration (server side).

This is the Server's view of the Pad + Jetson-runner workstation topology from
``PRD_Pad_UI_CV_Jetson_QCModel_Inference.md`` and the headless-pairing P0
addendum:

* a **workstation = one Pad + one paired Jetson runner** (``device_type =
  jetson_runner``); one Jetson serves one Pad (1:1);
* the Jetson runs qc-model inference only, **never talks to the Server** — all
  reporting (pairing binding, health) flows through the Pad on sync
  (offline-tolerant: pairing itself never requires Server reachability);
* the production Jetson is **headless** — no display, keyboard or mouse — so all
  status surfaces on the Pad, and pairing never uses a screen/QR (USB physical
  proof or a Wi-Fi pairing-window + chassis-fingerprint check);
* Jetson output is **evidence, not authority** — the Server still recomputes the
  final verdict (S4).

The pure Pad↔Jetson LAN interaction (key exchange, signed inference requests,
re-pair fail-closed) lives in the ``jetson_runner`` mock component; this package
owns the Server-side binding record, health surfacing and readiness resolution.
"""
