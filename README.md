# Giraffe QC Model

On-device-first visual quality-control product for Giraffe Technology's
apparel/textile QC workflows. A QC operator captures a photo on an
Android phone or pad; the device compares it against that SKU's
standard reference photo using a small Qwen vision-language model
running **on the device itself**, and only escalates to a cloud model
(DashScope/Qwen API) when the on-device result is uncertain, times out,
fails to parse, or the device is overloaded. Uncertain results are
never silently treated as a pass.

> **Module relationship:** this repository is a **sub-module of the
> abcdYi product line**, not a standalone product with an optional
> integration. It is independently deployed (separate codebase,
> separate release cycle, separate database by default) but its
> product semantics — SKU identity, order/asset linkage, and event
> emission — depend on and extend abcdYi's data model. Treat any
> change to shared concepts (SKU, order, asset identity) as a change
> that must stay compatible with abcdYi, not a locally-owned decision.
> This mirrors how the GPM (Giraffe Pricing Model) module relates to
> the main platform: logically attached, physically separate.

> **Status: active development.** This README describes the target
> architecture and the current state as of the last update. Some
> components are implemented against simulated/mock inference; others
> are still in progress. See [Current state](#current-state) below
> before assuming any specific module is production-ready.

## Why on-device, not server-side

Earlier designs for this project assumed local inference would run on
a separate backend node calling an OpenAI-compatible endpoint. That
assumption was replaced: the product requirement is a **single APK,
installable by a normal user with no root and no separate server**,
running on mainstream Snapdragon-driven phones/pads. That constraint
rules out larger models (tens of seconds to minutes even on flagship
Snapdragon hardware with a dedicated mobile inference engine) and
points to a compact (4B parameter), heavily quantized model run through
**MNN** (Alibaba's open-source mobile inference engine), accepting that
a model this size needs more frequent escalation to human review or
cloud fallback than a server-grade model would.

This tradeoff is acceptable here because real QC inspections in this
product are narrow, single-SKU comparisons (one captured photo vs. that
SKU's known-good standard photo, checked against a short, predefined
QC point checklist) — not open-domain visual reasoning.

## Core safety principle

The single rule every module in this repository is built around:

> **Uncertainty must surface as `review_required`, never silently
> resolve to `pass`.**

This applies whether the uncertainty comes from a missing image, an
unparseable model response, an unrecognized QC point, an on-device
timeout, an unavailable cloud fallback, or anything else. No code path
should convert "we don't know" into "it's fine."

## Architecture

```text
Android QC App (single APK, no root, no separate server required)
  ├── CameraX live camera, auto-capture with quality/stability gating
  ├── Local-first photo + metadata storage (Room)
  ├── On-device MNN runtime running a small Qwen VL model
  ├── Inspection router: on-device first, cloud fallback if allowed
  └── Result display, labeling which engine produced each result

giraffe-qc-model backend (this repo's Python service — a sub-module of
abcdYi: independently deployed, but its SKU/order/asset identity and
event schema are abcdYi's, not locally invented)
  ├── FastAPI
  ├── SKU / standard photo / QC point / inspection data model
  │     (SKU identity sourced from / kept compatible with abcdYi)
  ├── DashScope/Qwen cloud fallback provider
  └── abcdYi-compatible asset registry APIs + events
        (this is not an "integration point" bolted on after the fact —
        QC inspection results are abcdYi domain events by design)
```

Inference is the operative word for "on-device first": a device with
the model already provisioned can complete a full inspection with zero
network connectivity. The backend's role is aggregation, the cloud
fallback leg, and emitting results as abcdYi events — not running the
primary inspection.

## Repository structure

```text
giraffe-qc-model/
├── alembic/              # DB migrations
├── scripts/               # operational scripts, incl. benchmark_mnn.sh
├── src/
│   ├── cv/                 # classical CV comparator (pre-dates this effort)
│   ├── db/                 # SQLAlchemy models, session, config
│   ├── api/                 # FastAPI routers (in progress)
│   └── qwen/                 # QWEN provider abstraction, schema, parser,
│                              # DashScope cloud provider (in progress)
├── tests/
└── docs/
    ├── LOCAL_FIRST_QWEN_QC.md
    ├── DEPLOYMENT_LOCAL_QWEN.md
    ├── ANDROID_QC_APP.md
    └── API_CONTRACT.md
```

The Android app module and its MNN integration live alongside this
backend (see `docs/ANDROID_QC_APP.md` for the current module layout);
check that doc for the authoritative path, since the Android side is
being developed in parallel and its structure may be ahead of what's
summarized here.

## Current state

This section should be kept honest and current — update it as phases
land rather than letting it drift.

- [x] Phase 0 — repository audit complete; known prior issues (missing
  image paths defaulting to pass, standard photo overwrite, frozen
  settings at import time, silent failure-to-done transitions) were
  verified fixed in existing code.
- [x] QWEN inference schema, prompt builder, and parser (shared
  contract between on-device and cloud paths) implemented against
  simulated/mock providers.
- [x] Inspection router implemented with the on-device-first / fail-closed
  policy, including the `on_device_fail_is_final` guard, exercised
  against mock on-device and cloud providers.
- [x] Cloud fallback (DashScope) integration implemented and
  end-to-end tested against a real DashScope API key.
- [x] `scripts/benchmark_mnn.sh` written: ADB-based on-device latency
  benchmark targeting mainstream Snapdragon hardware, reporting
  p50/p95 against the 10-second-per-image budget.
- [ ] **Real on-device MNN benchmark not yet run.** The on-device
  inspector (`MnnQwenInspector`) is currently a stub; the real
  `nativeRunInference()` JNI call against an MNN-converted model
  (default model: Qwen3-VL-4B-Instruct-MNN) has not been
  exercised on physical hardware. This is the next concrete
  milestone — see [Next milestone](#next-milestone).
- [ ] Android app's full capture → on-device-inspect → router →
  result-display flow has been validated in a simulated
  environment; it has not yet been installed and run on a physical
  device.
- [ ] Multi-tenant isolation and the rest of the Phase 9 test matrix:
  confirm current pass status directly from the latest CI run
  rather than assuming based on this document.

## Next milestone

Once a physical Snapdragon test device is available:

1. Provision the Qwen3-VL-4B-Instruct-MNN model on the device per
   `docs/DEPLOYMENT_LOCAL_QWEN.md`.
1. Run `./scripts/benchmark_mnn.sh` against it and record p50/p95
   latency, cold-start time, and peak memory.
1. If the 10-second-per-image budget is met, replace the
   `MnnQwenInspector` stub with the real JNI-backed implementation.
   If it is not met, do not relax the budget silently — report the
   measured numbers and choose a mitigation (smaller/more quantized
   model, reduced input resolution, or a narrower per-call scope)
   before proceeding.
1. Install the APK on the physical device and validate the full
   capture-to-result flow end-to-end, offline.

## Development principles

A few project-wide rules worth knowing before contributing:

- **Never commit model weights or other large binary model artifacts**
  into this repository's normal git history. Model provisioning is a
  documented, scripted fetch (bundled at build time or downloaded and
  checksum-verified on first run) — see `docs/DEPLOYMENT_LOCAL_QWEN.md`.
- **Mock everything expensive in tests.** Unit/CI tests must never call
  the real MNN model or the real DashScope API. Use the deterministic
  fake providers/inspectors (`FakeOnDeviceQwenInspector`,
  `TimeoutOnDeviceQwenInspector`, `InvalidJsonOnDeviceQwenInspector`,
  `NotProvisionedOnDeviceQwenInspector`, and their Python-side
  equivalents for the cloud provider).
- **A failing test is a defect, not something to retry past.** The test
  suite is run 5 consecutive times before a change is considered done;
  a failure on any run stops the loop and gets reported, not silently
  re-run until it happens to pass.
- **Multi-tenant isolation is a hard requirement,** not an
  afterthought — any new endpoint or query touching `ProductStandard`,
  `StandardPhoto`, `QCPoint`, `CapturePhoto`, `InspectionRun`, or
  `QCAsset` must be covered by a cross-tenant-access-denied test.
  Tenant identity here should align with abcdYi's tenant/customer
  model rather than introducing a parallel definition of "tenant" —
  this module inherits abcdYi's tenant boundaries, it doesn't define
  its own.
- **SKU and order identity are not locally owned.** Don't invent a
  new SKU ID scheme or order reference format in this repo; reference
  abcdYi's existing identifiers so QC results can be correlated back
  to the order/SKU they belong to without a separate mapping table.
- **This feature branch (`feature/local-first-qwen-qc`) is not merged
  to `main` autonomously.** Merges happen after explicit human review.

## Related documentation

- `docs/LOCAL_FIRST_QWEN_QC.md` — full product/architecture spec
- `docs/DEPLOYMENT_LOCAL_QWEN.md` — on-device model provisioning and
  backend cloud-fallback configuration
- `docs/ANDROID_QC_APP.md` — Android app module layout and capture flow
- `docs/API_CONTRACT.md` — backend API contract for the Android app
  and any fleet-aggregation consumers
- abcdYi main platform docs — *[link to the canonical abcdYi
  architecture/event-schema reference here]*. Since this module
  inherits abcdYi's SKU/order/tenant identity and emits abcdYi-shaped
  events, that reference — not this README — is the source of truth
  for those shared concepts.

-----

## Instruction for Claude Code: publishing this README

> The section below is a standing instruction for Claude Code, not
> end-user documentation. Keep it in the file so the same instruction
> is available on every future README update, not just this one.

When asked to publish or update this README:

1. Replace the existing `README.md` at the repository root with the
   full content above (everything from the `# Giraffe QC Model` title
   down to this instruction section, inclusive — this instruction
   section itself should remain part of the file going forward).
1. Commit on the current feature branch (`feature/local-first-qwen-qc`),
   not on `main`. Use a clear commit message, e.g.:
   `docs: add project README describing on-device-first QC architecture and abcdYi module relationship`
1. Push the commit to the remote.
1. Do **not** merge this branch into `main` as part of this task —
   per existing branch discipline, merges happen only after explicit
   human review and approval.
1. Confirm the push succeeded and report back the commit hash and a
   link to the commit/diff.
1. If the `Current state` checklist above is stale relative to what
   you actually know about the repository at the time of this commit,
   flag the discrepancy in your report rather than silently editing
   the checklist to match — that section is intentionally maintained
   by humans reviewing actual CI/test results, not auto-updated by an
   agent's own assumptions.
