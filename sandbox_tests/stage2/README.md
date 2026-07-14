# Stage 2 — Jetson-like CV simulation and UI validation

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

Stage 1 is accepted and merged. Q1 selected QEMU aarch64 with `N1_WORK`; the
decision and its limits are recorded in `DECISION_RECORD.md`.

Stage 2 validates the standalone CV path in a Jetson-like environment and, by
explicit user requirement, the Pad-facing UI behavior driven by simulated CV
results. It does not use a real Jetson, real camera, or real-hardware performance
and power measurements.

The UI scope is limited to visible workflow behavior: simulator readiness,
fixture capture labeling, CV evidence display, explicit unavailable/error state,
and fail-closed presentation. It does not move UI logic onto Jetson and does not
claim real-hardware integration.

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
4. Exercise the six UI states in `UI_VALIDATION_PLAN.md` on an Android emulator
   using explicitly simulated fixtures and retain screenshots plus state payloads.
5. Run `runner.py` to compare the native and ARM64 CV outputs and generate
   `stage2_report.{json,md}` using the shared report schema.

Stage 2 performs no LLM/VLM call. Qwen may be a replaceable configured default in
other deployments; Giraffe QC is not a Qwen ecosystem product and Stage 2 makes
no model-quality claim.
