# Stage 2 — Jetson-like CV simulation and UI validation

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

Stage 1 is accepted and merged. Q1 selected QEMU aarch64 with `N1_WORK`; the
decision and its limits are recorded in `DECISION_RECORD.md`.

Stage 2 validates the standalone CV path in a Jetson-like environment and, by
explicit user amendment on 2026-07-15, the Pad-facing Web flow with either a
repository fixture or a **Mac-attached USB camera** as the simulated capture
source. A Mac USB camera is host input for the simulator; it is not a Jetson
camera and does not advance the project to Stage 3. Stage 2 does not use a real
Jetson or make real-hardware performance and power claims.

The product UI must use the PRD role entry (Administrator / Operator), switch
English and Chinese at any time, and control the real qc-model service: search
an executable SKU, create a database-backed inspection job, attach validated
evidence, submit the exact checkpoint set, run the deterministic fail-closed
finalizer, and load the persisted report. Stage 2 data is stored in the
configured `giraffe` database on CTYUN MySQL through the approved bridge; no
credential or infrastructure address is committed.

Required artifacts:

- selected simulation method and limitations in `DECISION_RECORD.md`;
- external-drive selection and RW evidence in `EXTERNAL_DRIVE_INVENTORY.md`;
- executable CV cases and generated `stage2_report.{json,md}`;
- UI evidence following `UI_VALIDATION_PLAN.md`;
- Stage 1 versus Stage 2 behavior differences in `DIFFERENCE_LIST.md`.

The code-level Q1 gate is in `gate.py`. It intentionally has no default method.

## Evidence workflow

1. Keep the Linux aarch64 base image, overlay, VM logs, and working copy under
   `/Volumes/N1_WORK/giraffe-stage2`; do not commit VM images.
2. Run `drive_probe.py` for a bounded, non-benchmark write/fsync/read-back check.
3. Run `cv_probe.py` once on the native host and once inside the QEMU aarch64
   guest. The guest runtime must identify as `aarch64` or `arm64`.
4. Start the qc-model Web service on Mac loopback, exercise the real role/login/
   job/capture/finalize/report flow in desktop Chrome, and record evidence per
   `UI_VALIDATION_PLAN.md`. `chrome_ui_server.py` remains supplemental evidence
   for the six simulator-state presentations; it is not the product control UI.
5. Run `runner.py` to compare the native and ARM64 CV outputs and generate
   `stage2_report.{json,md}` using the shared report schema.

Stage 2 performs no LLM/VLM call. Qwen may be a replaceable configured default in
other deployments; Giraffe QC is not a Qwen ecosystem product and Stage 2 makes
no model-quality claim.
