# Stage 3 scaffold

This directory is the Stage 3 branch for physical camera, real Xavier NX,
role-boundary, timing, and defocus/low-light/occlusion evidence. It carries
two separate gates that must not be conflated.

Stage 3 uses Group A only: Jetson-local CV plus a Jetson-local visual model,
as defined by `docs/STAGE3_AB_TESTING_SPEC.md`.

## Deployment preparation — may proceed now

Reflash, dependency install, MNN SDK/model asset pinning and verification,
service install, and the readiness self-check may all proceed in parallel
with Stage 2 acceptance. Follow, in order:

1. `docs/STAGE3_JETSON_PREDEPLOY_CHECKLIST.md`
2. `docs/STAGE3_AB_TESTING_SPEC.md` (the authoritative Group A definition)

## Stage 3 testing — requires the authorization gate to be open

Formal Stage 3 Group A testing may start **only** after the current
Stage 2 interactive acceptance has passed. This is a live, machine-checked gate:

```bash
python3 scripts/ci/stage3_authorization_gate.py
```

The gate reads `sandbox_tests/prd_traceability.json`'s `PRD-S2-30` entry: it
is open only when that entry is `verified` and points at an existing,
`passed`, non-mock, sufficiently-recent Stage 2 report. Run
`scripts/jetson_stage3_run_group_a.py` and it refuses to run (no report
written) when the gate reports closed — there is no flag to bypass this.

Additionally, before Group A may run, both of these must be independently
approved (checked automatically by `jetson_stage3_run_group_a.py`, not
by hand):

- `scripts/jetson_verify_mnn_lock.py` against `deploy/jetson/mnn-sdk.lock.json`
- `scripts/jetson_verify_model_manifest.py` against the deployed model's
  `model_manifest.json`

## What belongs here once both gates are open

Physical camera capture, real Xavier NX inference (Group A),
role-boundary verification, per-stage timing, and defocus/low-light/occlusion
evidence — all per `docs/STAGE3_AB_TESTING_SPEC.md` §3's report schema and
§4's minimum acceptance criteria. Reports land in
`sandbox_tests/reports/stage3_ab_*.json` and are checked by
`scripts/ci/stage3_ab_report_check.py`.
