# Giraffe QC Model — AI-Native Visual QC Intelligence

`Tablet / Pad` | `Server` | `Digital QC Worker Skill` | `Mature Skill Package` | `Training Pack` | `Rule Learning` | `Sample Learning` | `Readiness Gate` | `giraffe-language-skill` | `Fail Closed`

Giraffe QC Model is an AI-native quality control inference system for industrial procurement.

The repository contains a Tablet / Pad-side QC path, a server-side QC service, and a shared visual QC training foundation for SKU-specific inspection workflows.

At the product level, Giraffe QC Model is a trainable digital QC worker skill for LLM/VLM-based industrial inspection. It trains a digital QC worker for a specific SKU until the inspection skill reaches a mature, verified state. Once mature, the skill can be packaged, signed, and replicated across many Pad workstations, production lines, shifts, or factories without retraining each human operator or each device.

The product optimizes for per-SKU inspection accuracy, checkpoint-level evidence quality, human-AI agreement, false-pass reduction, traceability, and safe replication. It does not optimize for raw SKU count in the early phase.

---

## Digital QC Worker Skill Objective

Human QC workers must be trained individually. Their inspection quality varies by person, shift, fatigue, factory context, and experience. When a trained worker leaves, accumulated know-how is difficult to preserve or copy.

Giraffe QC Model turns SKU-specific QC know-how into a mature, signed, deployable digital worker skill:

```text
Train once
Verify once
Package once
Replicate many times
```

A mature QC skill package may include standard photos, process-card-derived facts, confirmed detection points, expected values, pass criteria, region annotations, required views, evidence requirements, known defect examples, provider/runtime requirements, qualification status, checksum, and signature.

The skill lifecycle is:

```text
Author -> Configure -> Confirm -> Publish -> Install -> Probation -> Mature -> Replicate -> Monitor -> Requalify
```

Only mature skills should be eligible for large-scale replication. New or changed skills must pass through assisted inspection, human final confirmation, agreement monitoring, and requalification gates before solo operation.

This is the core product goal: build reliable per-SKU QC skill maturity first, then replicate mature skills safely across many workstations.

---

## Product Boundary

Giraffe QC Model owns:

```text
Training Pack
Playbook
Capture Protocol
Digital Inspector
standard photos
operator QC requirements
source ingestion workbench
rule learning proposals
visual rule memory
sample learning
readiness and completeness gates
Pad / Server runtime profiles
QC result conventions
fail-closed review behavior
```

It does not own:

```text
RFQ execution
supplier routing
buyer/supplier messaging
OpenClaw channel credentials
GLTG lead-time simulation
GPM procurement reasoning
giraffe-db business fact ownership
commercial or legal approval
```

---

## P0 Language Boundary

Standard English is the only internal working language across Giraffe products.

QC source text can arrive in Chinese, Japanese, English, or other languages. Before QC workflow code extracts requirements, creates test points, proposes detection rules, builds decision packets, or writes graph data, raw multilingual text must pass through `giraffe-language-skill`.

Allowed path:

```text
raw multilingual QC requirement / process spec / operator note
-> giraffe-language-skill
-> canonical English QC requirement packet
-> QC source ingestion / rule proposal / training pack workflow
-> localized QC report or operator summary
```

The QC repository must not add its own multilingual product, material, defect, tolerance, count, view, or quality alias maps outside the shared language boundary.

If language-skill cannot produce a valid canonical packet, QC workflow must ask for clarification or mark the item `review_required`. It must not guess missing count, tolerance, threshold, view, material, or defect semantics.

---

## Runtime Architecture and Default Models

Giraffe QC Model is provider- and model-neutral. Qwen models are replaceable
deployment defaults, not required models, a product identity, or an ecosystem
dependency. LLM/VLM providers are selected through configuration and adapters.

Architecture v2 defaults:

| Runtime role | Default model | Responsibility |
|---|---|---|
| Cloud GPU (A10/V100 class) | `qwen3-vl-30b-A3B` | Production Operator VLM inference; provider is configurable. |
| Administrator Xavier NX | `qwen3-vl-4b` via MNN | Administrator-side recognition and standard-authoring assistance only. |
| Operator Pad + Jetson Nano | No VLM | Capture, OpenCV pre-analysis, crop/compress, upload, queue, and health telemetry. |

The Operator path sends bounded crops to the configured cloud inference
provider. It does not route production judgments through Xavier, and the Nano
does not host an LLM/VLM. Older Pad-local and Pad-to-Xavier runtime code remains
only as explicitly marked compatibility material until its scheduled removal;
it does not define the current product architecture.

Admin Studio (`/admin/studio`) independently configures a text assistant and a
vision assistant through the provider-neutral `STUDIO_TEXT_*` and
`STUDIO_VISION_*` settings. A deployment may currently choose Qwen defaults,
but the UI and domain services depend only on compatible adapter contracts.
Text turns draft structured QC requirements; reference-photo turns draft
visible inspection points. Both outputs remain pending until an authenticated
Administrator explicitly confirms them, and publication/installation are
separate human actions. Production fails closed when either requested assistant
is unconfigured or unavailable; the deterministic parser is test-only.

---

## Visual QC Foundation

The visual QC engine introduces:

```text
provider abstraction for configurable LLM/VLM adapters (Qwen is the default only)
SKU Training Pack
Playbook
Capture Protocol
Digital Inspector schemas
detection point category workflow
supervisor-confirmed categories
physical-measurement boundary enforcement
deterministic finalizer
capture-quality gate
fail-closed review_required behavior
human feedback schema
false-pass P0 escalation skeleton
admin UI at /admin/qc-model
chat-first Admin Studio at /admin/studio
```

Phase 1 validates structure and safety guardrails. It does not certify real-world visual accuracy, defect recall, or production readiness.

---

## Rule Learning

The rule-learning loop proposes structured detection points, visual features, pseudo-defects, decision rules, and review-required conditions from canonical operator requirements plus Training Pack context.

Rules:

```text
LLM/VLM proposes
supervisor approves
confirmed rules execute
unapproved proposals do not modify active Training Packs
physical-measurement checkpoints force record_only
missing count / tolerance / threshold / view becomes a question, not a hallucinated rule
provider failure fails closed
malformed model output persists zero proposals
```

Confirmed rules are executed through the configured runtime adapter. In
Architecture v2, Operator recognition uses the cloud adapter, while MNN is
limited to the Administrator Xavier node. Neither Qwen nor MNN is a required
product dependency; both are replaceable deployment defaults.

---

## Sample Learning

Sample learning builds structured visual rule memory from grouped sample images:

```text
reference
positive
defect
boundary
capture_artifact
```

Every observation preserves per-sample provenance, traceable to the exact image and optional region through an append-only evidence anchor.

Approval and apply are separate steps:

```text
approve visual rule memory
apply approved visual rule memory
reject non-approved memory
conflict -> 409
supervisor resolves conflict
never silently overwrite confirmed rules
```

---

## Readiness and Completeness Gate

Readiness is not structural only. `exam_ready`, `production_assisted` / L2, and `controlled_active` / L3 depend on confirmed, production-eligible QC knowledge.

Readiness requires:

```text
confirmed detection points
approved/applied visual rule memory or confirmed visual rule
production-eligible provider
sample coverage
closed pseudo-defect rules
closed capture-artifact rules
closed unresolved questions or audited waiver
qualification report for controlled_active
```

Mock, fake, stub, or skeleton-derived memory can never satisfy production readiness.

Unknown or cross-tenant packs fail closed.

---

## Production Deployment Hardening

Operational guarantees for real deployment. See [`docs/production-deployment.md`](docs/production-deployment.md).

```text
APP_ENV=production disables all mock/fake/test providers
production APIs fail closed when the real provider is unconfigured
GET /api/qc/production/provider-eligibility exposes provider eligibility
structured observability + metrics: GET /api/qc/production/metrics
append-only audit tables expose no PUT/PATCH/DELETE
supervisor identity required for every gated action
migrations 009 through 016 apply up/down/up cleanly
```

Mocked tests prove workflow only, not production visual accuracy. Production Assisted Mode (L2) requires a human final decision. Controlled Active Mode (L3) requires qualification and false-pass monitoring.

---

## Physical Measurement Boundary

If a ruler, fixture, gauge, caliper, scale, template, or other physical instrument is faster and more accurate, AI must not be the primary judge.

AI may record, route, or assist review, but physical measurement checkpoints must not be converted into visual pass/fail hallucinations.

---

## Operator Edge CV

The Operator workstation uses Pad + Jetson Nano for deterministic QC-point
detection, marking, cropping, and optional classical-CV evidence. The Nano runs
no LLM/VLM. Only bounded per-point crops are sent to the configured cloud VLM
service in one batch; full frames are prohibited.

CV evidence never becomes the verdict by itself. A CV failure is recorded and
the configured cloud VLM may continue without CV context when valid crops still
exist. If valid crops cannot be produced, or the cloud returns no response, the
job has no verdict and fails closed or remains visibly `pending_upload`.

CI uses labeled test doubles and fixtures only. Those tests demonstrate contract
and workflow behavior, not hardware readiness, visual accuracy, or cellular SLO
compliance.

---

## Administrator Xavier NX

The Xavier NX is an Administrator-side authoring and qualification node. It
runs CV plus a configurable local VLM through MNN; `qwen3-vl-4b` is the default
configuration, not a required model or ecosystem dependency. It is not in the
Operator production inference path and is never paired to the Pad as the
Operator verdict engine.

Any mock runner is explicitly labeled
`MOCK INFERENCE — NOT REAL QC JUDGMENT`, gated by configuration, and impossible
to enable in production mode. Physical Xavier validation remains a manual
hardware step until linked device evidence exists.

---

## Integration with Giraffe Stack

```text
giraffe-language-skill = canonicalizes multilingual QC text
giraffe-db             = stores business evidence and audit links
giraffe-agent / AIVAN  = routes workflow and approval
giraffe-qc-model       = owns QC intelligence
GLTG / GPM             = do not perform QC pass/fail
human supervisor       = approves rules, resolves ambiguity, accepts risk
```

---

## Required Tests

QC-related tests must prove:

```text
non-English QC text calls giraffe-language-skill before rule extraction
missing canonical packet blocks rule extraction
LLM/VLM cannot fabricate missing count/tolerance/view/threshold
physical-measurement guard forces record_only
provider failure fails closed
malformed JSON fails closed
sample provenance is preserved
approved and applied states are distinct
readiness cannot be satisfied by mock/stub data
controlled_active fails closed without qualification report
```

---

## Product Principle

QC must inspect confirmed detection points against approved visual evidence. A model-level pass can never override a checkpoint-level fail.

A mature QC skill is an industrial knowledge asset. The value of Giraffe QC Model is not that one Pad can inspect one item; the value is that a verified digital QC worker skill can be safely replicated across many workstations while preserving the same standard, evidence discipline, and qualification state.

---

## License

Proprietary. All rights reserved.

This repository is not open-source software. No copying, cloning, forking, redistribution, modification, deployment, use, benchmarking, integration, or derivative work is permitted without prior written authorization from Giraffe Technology.

Public visibility on GitHub, if enabled, grants only limited viewing through GitHub's standard web interface. It does not grant a license to reproduce, use, or redistribute the code or the digital QC worker skill logic.

See [`LICENSE`](LICENSE).
