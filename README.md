# Giraffe QC Model

AI-native quality control inference system for industrial procurement, with two coordinated deployment targets: an on-device Android Tablet app and a server-side QC model. Both share a strict no-fake-result policy and a common set of field/result conventions, so outputs from both ends remain comparable and auditable.

## Overview

|Target            |Model                   |Inference                                                |Network                       |
|------------------|------------------------|---------------------------------------------------------|------------------------------|
|Android Tablet App|Qwen3-VL-2B-Instruct-MNN|Local, via MNN runtime                                   |Fully offline                 |
|QC Model (Server) |Qwen3-VL-8B             |Local inference, with API fallback on capability overflow|Local-first, network on demand|

## Status

### Android Tablet App

✅ **Working end-to-end** — verified running on real Android Tablet hardware with actual MNN inference calls.

- Ships with a quantized **Qwen3-VL-2B-Instruct-MNN** model bundled into the app.
- Runs **fully offline**: no cloud dependency for SKU matching or QC inference.
- Branch: `android-pad-app`
- Task spec: `CLAUDE_ANDROID_PAD_ITER4A_TASK.md`

### QC Model (Server)

Configured with **Qwen3-VL-8B** as the primary inference model.

- Runs locally by default.
- When local model confidence/capability is insufficient ("capability overflow") for a given case, the server falls back to a cloud API call to supplement the result.
- Cloud calls are a fallback path only — not the default inference route.

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

## Core Principles

- **No fake results.** The system never fabricates a pass/fail outcome.
- **No silent cloud fallback.** Cloud inference is only invoked on local capability overflow, and is never the default path.
- **No silent degradation.** If the Tablet app's MNN runtime is unavailable, the result must be explicitly marked `MNN pending` / `review_required` rather than defaulting to any pass/fail value.

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
├── tests/                 # 203 Python unit tests + 6 opt-in integration tests
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
- [x] Full Python test suite: **203 tests pass 5× consecutively**, 6
  Qwen integration tests skipped by default (require
  `RUN_QWEN_INTEGRATION=1` + real key)
  (latest run on branch `claude/new-session-0rw6k5`).
- [x] **Real on-device MNN inference confirmed.** MNN model invocation
  has been verified running end-to-end on a physical test tablet (real
  Android device, not emulator/simulator).
- [x] Android app installed and validated on a physical device. The
  capture → on-device-inspect → router → result-display flow confirmed
  end-to-end on real hardware.

## Next milestone

✅ **Physical-device validation complete.** The capture-to-result flow has been
confirmed running end-to-end on a real Snapdragon test tablet (offline, real
Android hardware). Qwen3-VL-2B-Instruct-MNN was confirmed running on-device via
the MNN runtime.

No benchmark numbers (p50/p95 latency, cold-start time, peak memory) are
recorded in this repository — run `./scripts/benchmark_mnn.sh` on the physical
device to capture them. If p95 exceeds the 10 s budget, do not relax the
budget: report the numbers and choose a mitigation (smaller model, lower
resolution, or narrower per-call scope) before proceeding.

## Development setup

### Quick start

```bash
# Install runtime + dev tooling
make sync-dev          # or: uv sync --group dev

# Run the full test suite once
make test              # or: uv run pytest tests/ -v

# Run 5× consecutively (required before declaring a change done)
make test5
```

> **Do not use bare `uv sync` before running tests.** Plain `uv sync`
> installs only runtime dependencies and will silently remove pytest
> from the virtual environment. Always use `uv sync --group dev`
> (or `make sync-dev`) when you need to run the test suite.

### Equivalent direct commands

```bash
uv sync --group dev
uv run pytest tests/ -v
```

### Qwen cloud integration tests (opt-in)

The Qwen real-API integration tests are **skipped by default** unless all
of the following environment variables are set:

| Variable | Required value |
|----------|---------------|
| `RUN_QWEN_INTEGRATION` | `1` |
| `QC_ENGINE_MODE` | `cloud_qwen_dev` |
| `LLM_ENABLE_REAL_CALLS` | `true` |
| `QWEN_CLOUD_ENABLED` | `true` |
| `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN` | `true` |
| `DASHSCOPE_API_KEY` or `QWEN_API_KEY` | real key |

Skipped integration tests are **expected and correct** in normal CI runs.

To run them manually:

```bash
RUN_QWEN_INTEGRATION=1 \
QC_ENGINE_MODE=cloud_qwen_dev \
LLM_ENABLE_REAL_CALLS=true \
QWEN_CLOUD_ENABLED=true \
ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true \
DASHSCOPE_API_KEY="$DASHSCOPE_API_KEY" \
uv run pytest tests/integration/ -v
```

Or via Makefile (omits the key — set `DASHSCOPE_API_KEY` in your shell first):

```bash
make test-qwen
```

The `DASHSCOPE_API_KEY` / `QWEN_API_KEY` is a runtime-only secret.
It must never be committed to this repository.

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
