# Giraffe QC Model

Provider-neutral, local-first multimodal quality-control inference system for industrial procurement.

Giraffe QC Model uses **Qwen as the default multimodal provider** because it currently offers a strong local/cloud deployment path for visual QC, including Android MNN and DashScope fallback. However, this project is **not a Qwen ecosystem product**. The product logic, API contracts, schemas, routing policy, evidence model, and database layer must remain independent of any single LLM provider.

The long-term target is a multimodal QC engine that can switch between Qwen, local MNN, OpenAI, Anthropic, classical CV, mock providers, or future vision-language models without changing the QC product workflow.

---

## Overview

| Layer | Default implementation | Role | Provider lock-in |
|---|---|---|---|
| Android Tablet App | Qwen3-VL-2B-Instruct-MNN via MNN runtime | Offline, on-device visual QC | No — exposed through a local inspector interface |
| Backend QC Service | Provider-neutral multimodal QC service | Fleet aggregation, audit, fallback, reporting, abcdYi integration | No — provider selected by config |
| Default Cloud Adapter | Qwen / DashScope | Cloud fallback for capability overflow and development validation | Replaceable |
| Future Adapters | OpenAI, Anthropic, local server models, custom VLMs | Alternative multimodal reasoning providers | Replaceable |

The operative product concept is **provider-neutral multimodal QC**, not Qwen integration. Qwen is simply the current default adapter.

---

## Product Direction

Giraffe QC Model is designed to inspect production photos against known-good SKU standards and structured QC points. It must produce auditable, evidence-based results:

- `pass`
- `fail`
- `review_required`

The system should not merely ask a model to "compare two images." It should call multimodal capabilities in a structured way:

1. **Image quality assessment** — determine whether the captured photo is usable.
2. **SKU / standard matching** — verify that the captured product matches the selected SKU or standard.
3. **QC inspection** — evaluate each QC point against standard photos and production photos.
4. **Defect grounding** — localize visual evidence using normalized regions / bounding boxes where possible.
5. **OCR / label extraction** — read labels, tags, packaging text, serial numbers, or compliance marks when required by a QC point.
6. **QC report generation** — generate bilingual human-readable reports strictly from structured results.

These capabilities should be exposed through provider-neutral interfaces. Qwen-specific payloads, DashScope endpoints, or model names must remain inside provider adapters.

---

## Core Principles

- **Provider-neutral by design.** Qwen is the default provider, not a product dependency.
- **Local-first inspection.** On-device or local inference is preferred whenever available.
- **No fake results.** The system must never fabricate pass/fail outcomes.
- **No silent cloud fallback.** Cloud calls require explicit configuration and must be recorded as fallback.
- **No silent degradation.** If a local runtime is unavailable, the result must be explicitly marked `review_required`, `MNN pending`, or equivalent.
- **Evidence-first output.** QC decisions must include structured evidence, not just natural-language explanations.
- **Fail-closed behavior.** Invalid model output, missing images, low confidence, hallucinated QC point IDs, or parser failures must become `review_required`, not `pass`.
- **No provider branding in product logic.** Public APIs and core schemas should not be tied to Qwen, DashScope, or any other provider.
- **Tenant isolation is mandatory.** No endpoint, query, inspection result, asset, or sync job may leak cross-tenant data.

---

## Current Implementation Status

This repository already contains a working foundation for local-first QC and Qwen/DashScope validation, but the provider-neutral capability layer is the next major refactor.

### Implemented foundation

- FastAPI QC API for standards, standard photos, QC points, captures, inspections, assets, sync targets, and inspection result retrieval.
- SQLAlchemy-based QC data model and migrations.
- Shared inspection result conventions: `pass`, `fail`, `review_required`.
- Qwen-specific schema, prompt builder, parser, router, fake providers, and DashScope cloud provider.
- Explicit cloud guards for Qwen/DashScope calls.
- Opt-in real Qwen/DashScope integration tests.
- Classical CV comparator layer from earlier iterations.
- Android Tablet app module scaffold with CameraX, SKU/capture flow, result display, local MNN runtime loader, and router logic.
- Android fake/mock test doubles kept in test sources, not production sources.
- Multi-tenant isolation tests.
- Never-convert-failure-to-pass invariant tests.

### Not yet complete

- Real on-device MNN inference has **not** been fully confirmed. JNI/native inference is scaffolded, but `nativeRunInference()` is not yet wired to the real MNN AAR path on a physical Snapdragon device.
- The current Qwen/DashScope providers are still partly Qwen-specific and need to be refactored into a provider-neutral multimodal provider interface.
- Structured visual evidence, defect grounding, image quality assessment, OCR extraction, and provider-neutral report generation are not yet fully separated into capability modules.

---

## Target Architecture

```text
QC API / Android App / Batch Jobs
        |
        v
MultimodalQCService
        |
        v
CapabilityRouter
        |
        +--> Deterministic checks / classical CV
        |
        +--> Provider-neutral multimodal capabilities
                |
                +--> Qwen / DashScope adapter        default
                +--> Local MNN adapter               edge / Android
                +--> OpenAI adapter                  future / optional
                +--> Anthropic adapter               future / optional
                +--> Mock provider                   CI / unit tests
                +--> Other VLM adapters              future
```

The backend should eventually expose a neutral internal structure such as:

```text
giraffe-qc-model/
├── src/
│   ├── api/                 # FastAPI routers
│   ├── cv/                  # deterministic local vision / classical CV
│   ├── db/                  # SQLAlchemy models, sessions, migrations
│   ├── multimodal/          # provider-neutral multimodal layer
│   │   ├── providers/       # qwen, openai, anthropic, local_mnn, mock
│   │   ├── capabilities/    # image_quality, sku_match, qc_inspection, grounding, OCR, report
│   │   ├── prompts/         # versioned prompt packs
│   │   ├── parsers/         # JSON extraction and schema validation
│   │   ├── router.py        # local-first / fallback policy
│   │   └── service.py       # product-facing multimodal QC service
│   └── qwen/                # legacy Qwen-specific wrappers during transition
├── apps/
│   └── android-qc/          # Android local-first inspection app
├── tests/
└── docs/
```

During the transition, existing `src/qwen/*` and `src/llm/*` modules may remain for backward compatibility, but new product logic should depend on the provider-neutral layer.

---

## Deployment Targets

### Android Tablet App

Target behavior:

- Single APK.
- No root requirement.
- No separate server requirement for individual inspection.
- Offline local inference when the model is provisioned.
- Local MNN runtime using a small quantized multimodal model.
- Explicit `review_required` when local inference is unavailable or uncertain.

Current state:

- Android module is present.
- MNN runtime loader and inspector scaffold are present.
- Native JNI inference remains pending.
- Physical Snapdragon device validation remains pending.

### Backend QC Model

Target behavior:

- Provider-neutral service.
- Local-first routing.
- Optional cloud fallback on capability overflow.
- Fleet-level aggregation and audit.
- abcdYi-compatible asset registry APIs and events.
- Structured evidence and raw provider metadata for audit.

Current state:

- FastAPI QC service exists.
- Qwen/DashScope fallback exists.
- Provider-neutral capability layer is the next milestone.

---

## Capability Model

The final inspection flow should be:

```text
1. Validate tenant, SKU, standard, capture, photos, and QC points.
2. Check file existence and image metadata.
3. Run image quality assessment.
4. If image unusable, return review_required / retake.
5. Run SKU / standard matching when candidate standards exist.
6. If wrong SKU is likely, return review_required.
7. Run deterministic CV prefilter where applicable.
8. Run provider-neutral multimodal QC inspection.
9. Run defect grounding for fail or review_required items.
10. Run OCR extraction where QC points require text recognition.
11. Merge evidence.
12. Apply final routing policy.
13. Persist inspection run, result, item results, evidence, fallback metadata, and assets.
14. Emit inspection completed event.
```

---

## Provider Selection

Provider selection must be controlled by environment variables, not hardcoded product logic.

Recommended future configuration:

```env
MULTIMODAL_PROVIDER=qwen
MULTIMODAL_ENABLE_REAL_CALLS=false
MULTIMODAL_TIMEOUT_SECONDS=60
MULTIMODAL_MAX_RETRIES=2
MULTIMODAL_DEFAULT_MODEL=

# qwen | openai | anthropic | local_mnn | mock | cv

QWEN_BASE_URL=https://dashscope.aliyuncs.com/api/v1
QWEN_MULTIMODAL_MODEL=
QWEN_API_KEY=
DASHSCOPE_API_KEY=

OPENAI_MULTIMODAL_MODEL=
OPENAI_API_KEY=

ANTHROPIC_MULTIMODAL_MODEL=
ANTHROPIC_API_KEY=

QC_ROUTING_MODE=local_first
QC_ALLOW_CLOUD_FALLBACK=false
QC_REQUIRE_USER_CONSENT_FOR_CLOUD=true
QC_ALLOW_SEND_IMAGES_TO_CLOUD=false
QC_CLOUD_CAN_OVERRIDE_LOCAL_FAIL=false
QC_MIN_PASS_CONFIDENCE=0.82
```

Rules:

- Default provider may be Qwen.
- Missing real provider credentials in real-call mode must raise a clear configuration error.
- Unit tests and CI must never call real cloud providers by default.
- Mock provider is allowed in CI only.
- Production mode must never silently fall back to fake results.

---

## Inspection Output Contract

Existing API responses must continue to expose:

```text
overall_result
confidence
engine
model_name
summary
fallback_used
fallback_reason
items
```

The next schema should add structured evidence:

```json
{
  "overall_result": "pass | fail | review_required",
  "provider": "qwen | openai | anthropic | local_mnn | mock | cv",
  "model_name": "...",
  "confidence": 0.0,
  "items": [
    {
      "qc_point_id": "...",
      "qc_point_code": "...",
      "name": "...",
      "result": "pass | fail | review_required",
      "confidence": 0.0,
      "reason": "...",
      "evidence": {
        "image_quality": {},
        "visual_regions": [],
        "defect_grounding": [],
        "ocr": {},
        "standard_reference": "...",
        "production_observation": "...",
        "model_reasoning_summary": "...",
        "review_required_reason": "..."
      }
    }
  ],
  "fallback": {
    "used": false,
    "reason": null
  },
  "summary": "..."
}
```

Result policy:

- `pass` only if every active QC point passes with sufficient confidence.
- `fail` if any QC point fails.
- `review_required` if any QC point is uncertain and no hard failure exists.
- Hallucinated QC point IDs must be rejected.
- Missing QC point results must be filled as `review_required`.
- Invalid model JSON must become `review_required`.

---

## Safety and Audit Policy

- Never log full API keys.
- Never store raw image base64 in database.
- Store image paths, hashes, inspection metadata, structured model output, and fallback metadata.
- Cloud fallback must record provider, model, latency, fallback reason, and policy config.
- If local result is `fail`, cloud cannot turn it into `pass` unless explicitly configured.
- Even when override is enabled, both local and cloud outputs must be preserved for audit.
- If image quality is insufficient, do not allow a pass result.
- If SKU mismatch is suspected, do not allow a pass result.

---

## Development Setup

### Python

```bash
# Install runtime + dev tooling
make sync-dev          # or: uv sync --group dev

# Run the full test suite once
make test              # or: uv run pytest tests/ -v

# Run 5x consecutively before declaring a change done
make test5
```

Do not use bare `uv sync` before running tests. Plain `uv sync` installs only runtime dependencies and may remove pytest from the virtual environment. Use `uv sync --group dev` or `make sync-dev` when running tests.

### Android

```bash
# Create MNN stubs for CI when real AAR/native libs are not available
bash scripts/download_mnn_android_libs.sh --ci-stubs

# Build padLocal debug APK + run unit tests
cd apps/android-qc
./gradlew :app:assemblePadLocalDebug :app:testPadLocalDebugUnitTest
```

---

## Real Provider Integration Tests

Real Qwen/DashScope integration tests must remain opt-in.

Example future configuration:

```env
RUN_MULTIMODAL_INTEGRATION=1
MULTIMODAL_PROVIDER=qwen
MULTIMODAL_ENABLE_REAL_CALLS=true
QC_ALLOW_CLOUD_FALLBACK=true
QC_ALLOW_SEND_IMAGES_TO_CLOUD=true
QWEN_API_KEY=...
# or DASHSCOPE_API_KEY=...
```

Existing Qwen-specific integration tests may continue to use:

```env
RUN_QWEN_INTEGRATION=1
QC_ENGINE_MODE=cloud_qwen_dev
LLM_ENABLE_REAL_CALLS=true
QWEN_CLOUD_ENABLED=true
ALLOW_SEND_IMAGES_TO_CLOUD_QWEN=true
DASHSCOPE_API_KEY=...
```

Do not claim real provider integration succeeded unless the opt-in integration test was actually run with a real key.

---

## Test Requirements

Before any PR is considered complete:

- Run the Python test suite.
- Run the Python test suite 5x consecutively.
- Run Android unit tests if Android code changed.
- Report exact commands.
- Report skipped integration tests clearly.

Required invariants:

- No real API call by default.
- Missing image path never produces pass.
- Invalid model JSON returns `review_required`.
- Hallucinated QC point IDs are rejected.
- Missing QC point IDs are filled as `review_required`.
- Invalid visual region coordinates are rejected.
- Cloud fallback requires explicit enablement.
- Cloud cannot override local fail by default.
- Provider can switch from Qwen to mock without changing product service code.
- Report generation cannot change inspection result.
- API keys never appear in logs or outputs.
- Tenant isolation is preserved.

---

## Roadmap

### Milestone 1 — Provider-neutral multimodal core

- Add `src/multimodal/`.
- Add provider-neutral request/response interfaces.
- Add provider registry.
- Add Qwen/DashScope adapter.
- Add mock provider.
- Keep legacy wrappers working.

### Milestone 2 — Capability modules

- Add image quality assessment.
- Add QC inspection capability.
- Add defect grounding.
- Scaffold SKU match, OCR extraction, and report generation.
- Add versioned prompt packs.
- Add strict parsers and validators.

### Milestone 3 — Router integration

- Integrate capability router into `/api/v1/qc/inspect`.
- Preserve existing API response fields.
- Add structured evidence output.
- Persist provider metadata and fallback metadata.

### Milestone 4 — Android MNN validation

- Wire real JNI/native MNN inference.
- Run physical Snapdragon device validation.
- Record p50/p95 latency, cold-start time, and peak memory.
- Only mark local MNN inference as complete after real device validation.

---

## Development Principles

- Do not commit model weights or large binary artifacts into normal git history.
- Mock expensive or external dependencies in unit tests.
- Keep deterministic fake providers in test code or clearly marked mock modules.
- Do not place fake pass/fail logic in production runtime paths.
- A failing test is a defect. Do not retry until it happens to pass.
- Keep README status honest and current.
- Keep provider-specific naming out of product-facing APIs.
- Prefer structured evidence over natural-language-only explanations.

---

## Related Documentation

- `docs/LOCAL_FIRST_QWEN_QC.md` — local-first QC architecture and current Qwen/MNN assumptions.
- `docs/DEPLOYMENT_LOCAL_QWEN.md` — on-device model provisioning and backend cloud fallback configuration.
- `docs/ANDROID_QC_APP.md` — Android app module layout and capture flow.
- `docs/API_CONTRACT.md` — backend API contract for Android and fleet aggregation consumers.

---

## One-line Positioning

Giraffe QC Model is a provider-neutral multimodal QC engine for industrial procurement, using Qwen as the default adapter while preserving local-first, auditable, fail-closed quality-control behavior.
