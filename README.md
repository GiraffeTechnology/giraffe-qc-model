# Giraffe QC Model

On-device-first visual quality-control product for Giraffe Technology's
apparel/textile QC workflows. A QC operator captures a photo on an
Android phone or pad; the device compares it against that SKU's
standard reference photo using a small Qwen vision-language model
running **on the device itself**, and only escalates to a cloud model
(DashScope/Qwen API) when the on-device result is uncertain, times out,
fails to parse, or the device is overloaded. Uncertain results are
never silently treated as a pass.

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
rules out larger models (3B+ multimodal models take tens of seconds to
minutes even on flagship Snapdragon hardware with a dedicated mobile
inference engine) and points to a small (≤2B parameter), heavily
quantized model run through **MNN** (Alibaba's open-source mobile
inference engine), accepting that a model this size needs more
frequent escalation to human review or cloud fallback than a
server-grade model would.

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

giraffe-qc-model backend (this repo's Python service — optional for
an individual device's inspection to work; required for fleet-level
aggregation, reporting, and abcdYi integration)
  ├── FastAPI
  ├── SKU / standard photo / QC point / inspection data model
  ├── DashScope/Qwen cloud fallback provider
  └── abcdYi-compatible asset registry APIs + events
```

Inference is the operative word for "on-device first": a device with
the model already provisioned can complete a full inspection with zero
network connectivity. The backend's role is aggregation and the cloud
fallback leg, not running the primary inspection.

## Repository structure

```text
giraffe-qc-model/
├── alembic/               # DB migrations
├── apps/
│   └── android-qc/        # Android app (Kotlin, Gradle)
│       └── app/src/
│           ├── main/kotlin/com/giraffetechnology/qc/
│           │   ├── qwen/        # inspector interface, prompt builder,
│           │   │                # result parser, router, MNN scaffold,
│           │   │                # model provisioning, fake inspectors
│           │   ├── benchmark/   # §4.3.0 ADB latency benchmark activity
│           │   └── MainActivity.kt
│           └── test/kotlin/...  # JVM unit tests (no device required)
├── scripts/
│   └── benchmark_mnn.sh   # ADB benchmark for Snapdragon / 2B model
├── src/
│   ├── cv/                # classical CV comparator (pre-dates this effort)
│   ├── db/                # SQLAlchemy models, session, config
│   ├── api/               # FastAPI routers
│   └── qwen/              # QWEN provider abstraction, schema, parser,
│                          # router, DashScope cloud provider, fake providers
├── tests/                 # 166 Python unit + integration tests
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
  policy, including the `on_device_fail_is_final` guard (§4.5.4),
  exercised against mock on-device and cloud providers.
- [x] Cloud fallback (DashScope) integration implemented and
  end-to-end tested against a real DashScope API key.
- [x] `scripts/benchmark_mnn.sh` written: ADB-based on-device latency
  benchmark targeting Snapdragon 8 Gen / 8 GB RAM device, reporting
  p50/p95 against the 10-second-per-image budget.
- [x] Android app module complete (simulated environment): all Kotlin
  source files written (`QwenInspector`, `QcPromptBuilder`,
  `QcResultParser`, `QwenInspectionRouter`, `MnnQwenInspector` scaffold,
  `MnnRuntimeLoader`, `ModelProvisioning`, `FakeInspectors`,
  `BenchmarkActivity`, `MainActivity`); 4 Kotlin JVM test files, 38
  test cases, runnable without a device.
- [x] §4.5.1–4.5.4 exhaustive branch coverage: every router decision
  path (on-device accept, timeout, parse failure, low confidence,
  on-device fail-is-final, cloud disabled, no provider, model not
  provisioned, double failure) exercised with deterministic fakes.
- [x] Multi-tenant isolation (12 tests) verified: cross-tenant reads
  return 404 (not 403), listing endpoints never leak other tenants'
  data.
- [x] Never-convert-failure-to-pass invariant verified across all
  failure modes via parametrized tests.
- [x] Full Python test suite: **166 tests pass 5× consecutively**
  (latest run on branch `claude/new-session-0rw6k5`).
- [ ] **Real on-device MNN benchmark not yet run.** The on-device
  inspector (`MnnQwenInspector`) is currently a stub; the real
  `nativeRunInference()` JNI call against an MNN-converted model
  (default candidate: Qwen2-VL-2B-Instruct-MNN) has not been
  exercised on physical hardware. This is the next concrete
  milestone — see [Next milestone](#next-milestone).
- [ ] Android app has not yet been installed and run on a physical
  device. The capture → on-device-inspect → router → result-display
  flow has been validated in a simulated environment only.

## Next milestone

Once a physical Snapdragon test device is available (target: Snapdragon
8 Gen, 8 GB RAM, 128 GB storage):

1. Provision the Qwen2-VL-2B-Instruct-MNN model on the device per
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
- **This feature branch (`claude/new-session-0rw6k5`) is not merged
  to `main` autonomously.** Merges happen after explicit human review.

## Related documentation

- `docs/LOCAL_FIRST_QWEN_QC.md` — full product/architecture spec
- `docs/DEPLOYMENT_LOCAL_QWEN.md` — on-device model provisioning and
  backend cloud-fallback configuration
- `docs/ANDROID_QC_APP.md` — Android app module layout and capture flow
- `docs/API_CONTRACT.md` — backend API contract for the Android app
  and any fleet-aggregation consumers
