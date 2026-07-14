# Stage 2 — Jetson-like CV simulation and UI validation

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

Stage 1 is accepted and merged. Stage 2 is now gate-ready, but execution remains
blocked on Q1: select one simulation method in `DECISION_RECORD.md` before any
simulator installation or external-drive write test.

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
