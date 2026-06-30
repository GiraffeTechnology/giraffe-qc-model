# Phase 1 — General-Purpose Visual QC Training & Execution Foundation

This document describes the Phase 1 foundation added under `src/qc_model/`
plus its UI/API integration. It is a **server-side / schema-side /
orchestration** foundation. It does **not** touch the physical Android Pad
MNN runtime.

## What this is

Giraffe QC Model is a **general-purpose, provider-compatible, LLM/VLM-driven
visual QC training and execution framework**. It is *not* a single-SKU
detector and *not* a Qwen ecosystem product.

The framework is product-category agnostic. Each **production** digital
inspector, however, is bound to:

- one SKU
- one workstation
- one confirmed QC Training Pack
- one Playbook version
- one capture protocol
- one qualification state

## Default runtime profiles (two, selected by environment)

| Environment      | Provider     | Model                | Role |
|------------------|--------------|----------------------|------|
| `desktop_pc_mnn` | `qwen3_5_vl` | `qwen3.5-vl-2b-mnn`  | default desktop/PC MNN visual reasoning profile |
| `server`         | `qwen3_5_vl` | `qwen3.5-vl-8b-int4` | default server visual reasoning profile |

Selection: `QC_VISION_RUNTIME_ENV` (`desktop_pc_mnn` | `server`). Unknown/unset
falls back to `server`. See `src/qc_model/runtime_profiles.py`.

The defaults are Qwen3.5-VL profiles, but product services depend only on the
abstract `VisionLanguageModelProvider` interface
(`src/qc_model/providers/base.py`). A mainstream LLM/VLM adapter
(`MainstreamVLMAdapter`) satisfies the same interface, and the registry
(`src/qc_model/providers/registry.py`) is the only place that knows a concrete
vendor class — imported lazily. A test
(`tests/test_provider_abstraction.py::test_product_services_do_not_import_qwen_specific_classes`)
statically asserts product modules never import the Qwen class.

## Android / MNN model mismatch (documented, NOT migrated)

Per PRD §3.2, the existing Android Pad MNN code and the server edition refer to
model names that differ from the new product-default profile names. This PR
**documents** the mismatch and **does not** change physical Pad inference.

| Location | Current model name | Product-default profile name |
|---|---|---|
| `apps/android-qc/**` (MNN runtime, prompt builder, provisioning, benchmark) | `Qwen3-VL-2B-Instruct-MNN` | `qwen3.5-vl-2b-mnn` (desktop_pc_mnn) |
| `src/runtime/editions.py` (`server` edition) | `Qwen3-VL-8B` | `qwen3.5-vl-8b-int4` (server) |

Notes:

- The existing `src/runtime/editions.py` (Pad vs Server editions) is **left
  unchanged** so existing edition tests and Android wiring keep passing. The
  new dual default profiles live alongside it in
  `src/qc_model/runtime_profiles.py`.
- Any runtime migration of the physical Android Pad MNN model is **out of
  scope** for Phase 1 and must be handled as a separate, audited change.

## Module map

```
src/qc_model/
  runtime_profiles.py          dual default profiles + env selection
  providers/
    base.py                    VisionLanguageModelProvider + request/response
    registry.py                profile -> provider (lazy vendor import)
    qwen3_5_vl.py              default Qwen3.5-VL adapter (fails closed in P1)
    mock_provider.py           scriptable mock for tests
    compat_provider.py         mainstream LLM/VLM adapter stub
  schemas/
    checkpoint.py              categories + AI roles + physical-measurement boundary
    detection_point.py         proposed + confirmed category workflow
    training_pack.py           Training Pack, Playbook, Capture Protocol
    digital_inspector.py       inspector + lifecycle states
    inspection.py              request/result/checkpoint/incidental/capture
    feedback.py                human feedback + misjudgment taxonomy
  lifecycle.py                 inspector state machine + output policy
  finalizer.py                 deterministic finalizer (model pass never overrides fail)
  capture_quality.py           capture quality gate
  boundary.py                  physical-measurement boundary helpers
  learning.py                  learning readiness skeleton
  exam.py                      qualification metrics + thresholds (false_pass==0)
  feedback_escalation.py       false-pass P0 escalation
  prompts.py                   system/inspection/boundary/evidence templates
  runner.py                    precondition -> provider -> finalize -> lifecycle
  classification_service.py    DB-backed checkpoint category confirmation
```

## Deterministic finalization (safety core)

The model-level `overall_result` is **never** trusted. `finalize()`
re-derives the authoritative verdict from checkpoint-level results plus
guardrails. Precedence (highest wins):

1. invalid / unparseable model output → `review_required`
2. capture quality unacceptable → `review_required`
3. any **critical** checkpoint fail → `fail`
4. any checkpoint `review_required` (incl. forced) → `review_required`
5. any checkpoint fail (non-critical) → `fail`
6. all required checkpoints pass → `pass`

Per-checkpoint guardrails force a single checkpoint to `review_required`
before the overall is computed: unconfirmed category, unsupported category,
non-visual category (AI is not the primary judge), evidence required but
missing, and any checkpoint the model never reported.

**A model-level `pass` can never override a checkpoint-level `fail`.**

## Digital inspector lifecycle

```
draft → training_pack_pending → learning → exam_ready
      → exam_failed | exam_passed → on_trial → active
      → suspended → retired
```

- `draft` / `training_pack_pending` / `learning` / `exam_ready` / `exam_failed`:
  no production inspection.
- `on_trial`: AI suggestion + **mandatory human review** on every result.
- `active`: `pass` / `fail` / `review_required` under guardrails.
- `suspended`: may only ever emit `review_required`.

## False-pass handling (P0)

Any `false_pass` human feedback is P0:

1. mark inspection as a P0 incident,
2. add the sample to the misjudgment library,
3. suspend the inspector (downgrade `on_trial` too),
4. require supervisor review,
5. require Training Pack / prompt update,
6. require requalification before returning to `active`.

See `src/qc_model/feedback_escalation.py`.

## UI / API integration (extends existing admin UI)

The existing FastAPI + Jinja2 admin UI (`/admin/samples`) is extended — not
replaced — with a Phase 1 panel at **`/admin/qc-model`** (linked from the
admin nav). It shows the two default runtime profiles, the inspector
lifecycle, and, for each existing SKU detection point, the proposed checkpoint
category, the confirmed category, the AI role, and a confirm/edit control.

JSON endpoints:

- `GET  /api/qc-model/runtime-profiles`
- `GET  /api/qc-model/checkpoint-categories`
- `GET  /api/qc-model/lifecycle`
- `GET  /api/qc/skus/{sku_id}/detection-points`
- `POST /api/qc/detection-points/{id}/confirm-category`

Persistence: `qc_checkpoint_classifications`
(`src/db/qc_model_models.py`, migration `007`) overlays the existing
`qc_detection_points` catalog with proposed/confirmed category data.

## What mocked tests prove (and do not)

Phase 1 mocked-provider tests validate **schema correctness, workflow,
parser/finalizer behaviour, lifecycle guardrails, and unsafe-output
rejection**. They do **not** validate real qwen3.5-vl visual accuracy,
real-world defect recall, or production QC readiness. Real model accuracy must
be validated later with labeled real-world sample sets.

## Out of scope (Phase 1)

Physical Android Pad MNN inference migration, real camera/MNN runtime changes,
production fine-tuning, full qwen3.5-vl accuracy certification, large-scale
sample collection, supervisor/admin console rewrite, automatic legal QC
sign-off, automatic pass release without audit trail, and any fake-pass
production adapter.
