# Giraffe QC Model

AI-native quality control inference system for industrial procurement. The repository contains a Tablet / Pad-side QC app, a server-side QC service, and a shared visual QC training foundation for SKU-specific inspection workflows.

At the product level, Giraffe QC Model is a **general-purpose, provider-compatible, LLM/VLM-driven visual QC training and execution framework**. It is product-category agnostic at the framework layer, but every production digital inspector is **SKU-specific**, **workstation-specific**, and bound to a confirmed Training Pack, Playbook, capture protocol, and qualification state.

The artificial-flower accessory is only a seed SKU used to validate the pipeline. It is not the product scope. The chain-link-count case is a boundary example: if a ruler, fixture, gauge, caliper, scale, or template is faster and more accurate, AI must not be the primary judge.

## Product default model profiles

The product has two default Qwen3.5-VL runtime profiles:

| Runtime profile | Product default model | Intended runtime | Notes |
|---|---|---|---|
| `tablet_mnn` | `qwen3.5-vl-2b-mnn` | Tablet / Pad local MNN | Local visual QC profile for edge-side inspection. Physical Android Pad MNN migration remains separately audited. |
| `server` | `qwen3.5-vl-8b-int4` | Server-side QC model | Larger server profile for backend visual reasoning when explicitly configured. |

These are product defaults, not a Qwen ecosystem lock-in. Product services depend on a provider abstraction, not Qwen-specific classes, so mainstream LLM/VLM providers can be added through adapters.

Environment selection for the Phase 1 visual QC engine:

```bash
QC_VISION_RUNTIME_ENV=tablet_mnn   # qwen3.5-vl-2b-mnn
QC_VISION_RUNTIME_ENV=server       # qwen3.5-vl-8b-int4
```

Unknown or unset `QC_VISION_RUNTIME_ENV` falls back to `server`.

> Runtime naming note: the edge profile is **tablet**, not desktop. Do not use `desktop_pc_mnn` for this product path.

## Existing Pad vs Server edition config

The repository also contains an older edition switch in `src/runtime/editions.py`:

```bash
QC_RUNTIME_EDITION=padLocal|server
```

This remains in place for existing Pad / Server behavior. It is intentionally separate from the new Phase 1 visual QC runtime profile layer in `src/qc_model/runtime_profiles.py`.

Current Android / MNN code may still reference model names such as `Qwen3-VL-2B-Instruct-MNN`, while the product default tablet profile is `qwen3.5-vl-2b-mnn`. This mismatch is documented and must not be silently migrated inside server/schema-only PRs.

## Overview

| Target | Model / profile | Inference | Network |
|---|---|---|---|
| Android Tablet App | Existing Android MNN runtime; product target profile `qwen3.5-vl-2b-mnn` | Local MNN path, real JNI inference wiring still pending | Fully offline |
| QC Model Server | Product target profile `qwen3.5-vl-8b-int4` | Server provider path, fail-closed by default | Network only when explicitly configured |
| Visual QC Training Engine | Provider abstraction + Training Pack + deterministic finalizer | Schema / orchestration foundation in Phase 1 | Provider-compatible |

## What the visual QC engine does

The Phase 1 visual QC foundation lives under `src/qc_model/` and is described in [`docs/QC_MODEL_PHASE1_VISUAL_QC.md`](docs/QC_MODEL_PHASE1_VISUAL_QC.md). It introduces:

- dual default runtime profiles: `tablet_mnn` and `server`;
- provider abstraction for Qwen3.5-VL and mainstream LLM/VLM adapters;
- SKU Training Pack, Playbook, Capture Protocol, and Digital Inspector schemas;
- detection point category workflow with proposed and supervisor-confirmed categories;
- physical-measurement boundary enforcement;
- deterministic finalizer: model-level `pass` can never override checkpoint-level `fail`;
- capture-quality gate and fail-closed `review_required` behavior;
- digital inspector lifecycle skeleton;
- human feedback schema and false-pass P0 escalation skeleton;
- existing FastAPI + Jinja2 UI extension at `/admin/qc-model`.

Phase 1 validates **structure and safety guardrails**. It does not certify real-world Qwen3.5-VL inspection accuracy, defect recall, or production readiness. Real accuracy must be validated later with labeled real-world sample sets.

## Visual QC boundary

Giraffe QC Model focuses on visual signal interpretation under fixed SKU / fixed workstation conditions:

```text
standard image + qualified samples + defect samples + boundary samples
→ confirmed detection points
→ visual evidence
→ pass / fail / review_required
```

The model should distinguish:

- true quality defects;
- normal material behavior;
- reflection, shadow, blur, exposure, angle, or other capture artifacts;
- uncertainty requiring human review.

Examples of visual QC targets:

- missing rhinestone or missing component;
- pearl hairline crack;
- edge chip or surface scratch;
- color deviation or stain;
- glue overflow;
- deformation or assembly misalignment;
- reflection abnormality;
- texture or edge discontinuity;
- incidental visible abnormality outside the requested checklist.

Examples that should not be AI-primary:

- length, width, height, thickness;
- weight;
- hole diameter;
- spacing;
- chain link count;
- angle, hardness, tensile force;
- chemical or laboratory test results.

For physical measurement checkpoints, AI may record evidence, guide the operator, archive measurement results, or flag missing measurement proof. It must not be the primary judge.

## Core principles

- **Learn before work.** A digital inspector cannot inspect a production SKU until the Training Pack, Playbook, detection points, and qualification state are confirmed.
- **No fake production results.** Fake providers are test-only and blocked in default production runtime.
- **No silent cloud fallback.** Cloud/server inference is invoked only when explicitly configured.
- **No silent degradation.** If Tablet MNN runtime is unavailable, the result must be marked `review_required` / pending, never silently passed.
- **No pass without evidence.** Missing standard photos, missing detection points, invalid model output, missing evidence, disabled provider, or unreadable capture must return `review_required`.
- **No AI-primary physical measurement.** Physical measurement checkpoints are record-only / operator-guidance for AI.
- **False pass is P0.** Any human-confirmed false pass must trigger escalation, inspector downgrade/suspension, Training Pack update, and requalification.

## Architecture

```text
Android QC Tablet App
  ├── CameraX capture and quality/stability gating
  ├── Local-first photo + metadata storage
  ├── Tablet / Pad MNN runtime target: qwen3.5-vl-2b-mnn
  ├── Manual SKU/task fallback when visual matching is unavailable
  └── Result display with explicit engine/source labeling

giraffe-qc-model backend
  ├── FastAPI
  ├── SKU / standard photo / QC point / inspection data model
  ├── QC Sample Admin UI (/admin/samples)
  ├── Visual QC Phase 1 admin panel (/admin/qc-model)
  ├── Provider abstraction for Qwen3.5-VL + mainstream LLM/VLM adapters
  ├── Training Pack / Playbook / Digital Inspector schemas
  ├── Deterministic finalizer and fail-closed result handling
  └── Fleet aggregation, reporting, and abcdYi integration
```

## Repository structure

```text
giraffe-qc-model/
├── alembic/               # DB migrations
├── apps/
│   └── android-qc/        # Android Tablet app (Kotlin, Gradle)
├── scripts/
│   ├── benchmark_mnn.sh
│   └── download_mnn_android_libs.sh
├── .github/workflows/
│   ├── tests.yml
│   └── android-pad-ci.yml
├── src/
│   ├── api/               # FastAPI routers
│   ├── cv/                # classical CV comparator
│   ├── db/                # SQLAlchemy models, session, config
│   ├── qc_model/          # Phase 1 visual QC training engine foundation
│   │   ├── providers/     # provider abstraction, Qwen adapter, mainstream adapter, mocks
│   │   ├── schemas/       # Training Pack, detection point, inspector, inspection, feedback
│   │   ├── runtime_profiles.py
│   │   ├── finalizer.py
│   │   ├── lifecycle.py
│   │   ├── runner.py
│   │   ├── feedback_escalation.py
│   │   └── prompts.py
│   ├── qwen/              # existing Qwen provider/parser/router code path
│   ├── runtime/           # existing padLocal/server edition config
│   └── web/               # Jinja2 templates + static assets
├── tests/
└── docs/
    ├── QC_MODEL_PHASE1_VISUAL_QC.md
    ├── LOCAL_FIRST_QWEN_QC.md
    ├── DEPLOYMENT_LOCAL_QWEN.md
    ├── ANDROID_QC_APP.md
    ├── API_CONTRACT.md
    ├── QC_SAMPLE_DB_API.md
    └── QC_SAMPLE_ADMIN_UI.md
```

## Current state

- [x] QC Sample DB and SKU API implemented: `qc_sku_items`, `qc_standard_photos`, `qc_inspection_requirements`, `qc_detection_points`; `/api/v1/sku/search`; `/api/v1/sku/{sku_id}`.
- [x] Shared QC Sample Admin UI at `/admin/samples`: create SKU, upload/register photos, set primary photo, add requirements, draw ROI detection points, archive SKU.
- [x] Existing Pad vs Server edition config in `src/runtime/editions.py`: `QC_RUNTIME_EDITION=padLocal|server`.
- [x] Production-safety server behavior: disabled provider, fake provider outside test mode, unreadable photos, missing standard photos, zero detection points, parser inconsistency, and incomplete model output fail closed to `review_required`.
- [x] Android Tablet module scaffolded with CameraX, capture, SKU selection, prompt/parser/router, MNN runtime loader, model provisioning, benchmark activity, and JVM tests.
- [x] Fake/mock Android test doubles live under test sources only, not main production sources.
- [x] Phase 1 visual QC training engine foundation added under `src/qc_model/`: runtime profiles, provider abstraction, Training Pack schema, category confirmation, lifecycle, finalizer, feedback escalation skeleton, prompts, runner, and `/admin/qc-model` UI extension.
- [x] Dual product-default visual QC profiles defined: `tablet_mnn → qwen3.5-vl-2b-mnn`, `server → qwen3.5-vl-8b-int4`.
- [ ] Real Tablet / Pad MNN inference not yet confirmed. JNI native integration is scaffolded but physical device validation remains pending.
- [ ] Real qwen3.5-vl visual accuracy certification is not complete. Mocked tests validate structure and safety, not production defect-detection accuracy.
- [ ] Full Training Pack production workflow, real sample coverage, trial-shift policy, and supervisor review loop still need later iterations.

## Next milestones

### 1. Fix Phase 1 foundation blockers before merge

PR #19 is a foundation PR and should not be merged solely because CI is green. Before merge, verify or implement:

1. `run_inspection()` must enforce confirmed / qualified Training Pack status.
2. `request`, `TrainingPack`, and `DigitalInspector` must agree on `sku_id`, `station_id`, and `training_pack_id`.
3. Human feedback and false-pass escalation must be reachable through API/UI, not only schema/function code.
4. Qualification / activation must enforce that insufficient sample coverage can only enter `on_trial`, not `active`.
5. Finalizer capture-quality precedence must match the documented policy.
6. Runtime profile naming must remain `tablet_mnn`, not `desktop_pc_mnn`.

### 2. Validate Tablet MNN runtime

Once a physical Snapdragon Tablet / Pad test device is available:

1. Provision the current local MNN model according to `docs/DEPLOYMENT_LOCAL_QWEN.md`.
2. Run `./scripts/benchmark_mnn.sh` and record p50/p95 latency, cold-start time, and peak memory.
3. Validate the full capture-to-result flow offline.
4. If the latency or memory budget is not met, do not silently relax the budget; choose a mitigation such as smaller quantization, reduced input resolution, or narrower per-call scope.

### 3. Validate real visual QC accuracy

Use labeled real-world sample sets:

1. qualified samples;
2. true defect samples;
3. boundary / pseudo-defect samples;
4. capture-artifact samples;
5. human-reviewed false-pass / false-fail cases.

Do not treat mocked-provider tests as proof of production QC accuracy.

## Development setup

### Quick start

```bash
# Install runtime + dev tooling
make sync-dev          # or: uv sync --group dev

# Run the full test suite once
make test              # or: uv run pytest tests/ -v

# Run 5× consecutively before declaring a change done
make test5
```

> Do not use bare `uv sync` before running tests. Plain `uv sync` installs only runtime dependencies and may remove pytest from the virtual environment. Use `uv sync --group dev` or `make sync-dev` when running tests.

### Android Tablet

```bash
# Create MNN stubs for CI, no real AAR needed
bash scripts/download_mnn_android_libs.sh --ci-stubs

# Build padLocal debug APK + run unit tests
cd apps/android-qc && ./gradlew :app:assemblePadLocalDebug :app:testPadLocalDebugUnitTest
```

### Admin UI

```bash
uv sync --group dev
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8080

# Existing sample DB admin
# http://127.0.0.1:8080/admin/samples

# Phase 1 visual QC training engine panel
# http://127.0.0.1:8080/admin/qc-model
```

### Qwen cloud integration tests, opt-in

The Qwen real-API integration tests are skipped by default unless all of the following environment variables are set:

| Variable | Required value |
|---|---|
| `RUN_QWEN_INTEGRATION` | `1` |
| `QC_ENGINE_MODE` | `cloud_qwen_dev` |
| `LLM_ENABLE_REAL_CALLS` | `true` |
| `QWEN_CLOUD_ENABLED` | `true` |
| `ALLOW_SEND_IMAGES_TO_CLOUD_QWEN` | `true` |
| `DASHSCOPE_API_KEY` or `QWEN_API_KEY` | real key |

## Development principles

- Never commit model weights or large binary model artifacts into normal git history. Model provisioning must be scripted or sideloaded.
- Never commit uploaded sample images. `data/qc_samples/` is ignored; only metadata should be stored in the DB.
- Mock everything expensive in tests. Unit/CI tests must never call the real MNN model or a real cloud VLM provider unless explicitly gated.
- Fake providers and fake inspectors are test-only. They must never produce production pass/fail results in default runtime.
- A failing test is a defect. Do not rerun past a failure until it happens to pass.
- Multi-tenant isolation is a hard requirement. Any endpoint or query touching tenant-scoped QC data must have cross-tenant-access-denied coverage.
- Do not call Qwen API or DashScope from the Tablet QC inference path. Tablet-side QC inference must use local MNN runtime unless an explicit later design changes that boundary.
- The sample DB and admin page are edition-agnostic. Only inference behavior may differ per runtime edition/profile.
- Mocked-provider tests do not prove model visual accuracy. Accuracy must be validated with labeled real-world samples.

## Related documentation

- `docs/QC_MODEL_PHASE1_VISUAL_QC.md` — Phase 1 visual QC training engine foundation
- `docs/LOCAL_FIRST_QWEN_QC.md` — local-first Qwen QC product/architecture spec
- `docs/DEPLOYMENT_LOCAL_QWEN.md` — on-device model provisioning and backend cloud-fallback configuration
- `docs/ANDROID_QC_APP.md` — Android Tablet app module layout and capture flow
- `docs/API_CONTRACT.md` — backend API contract for Android app and fleet aggregation consumers
- `docs/QC_SAMPLE_DB_API.md` — QC sample catalog schema and SKU API reference
- `docs/QC_SAMPLE_ADMIN_UI.md` — shared admin web interface for managing samples
