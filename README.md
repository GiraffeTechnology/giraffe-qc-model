# Giraffe QC Model — AI-Native Visual QC Intelligence

`Tablet / Pad` | `Server` | `Training Pack` | `Rule Learning` | `Sample Learning` | `Readiness Gate` | `giraffe-language-skill` | `Fail Closed`

Giraffe QC Model is an AI-native quality control inference system for industrial procurement.

The repository contains a Tablet / Pad-side QC path, a server-side QC service, and a shared visual QC training foundation for SKU-specific inspection workflows.

At the product level, Giraffe QC Model is a general-purpose, provider-compatible, LLM/VLM-driven visual QC training and execution framework. It is product-category agnostic at the framework layer, but every production digital inspector is SKU-specific, workstation-specific, and bound to a confirmed Training Pack, Playbook, capture protocol, and qualification state.

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

## Runtime Profiles

Product default runtime profiles:

| Runtime profile | Product default model | Intended runtime | Notes |
|---|---|---|---|
| `tablet_mnn` | `qwen3.5-vl-2b-mnn` | Tablet / Pad local MNN | Local visual QC profile for edge-side inspection. Physical Android Pad MNN migration remains separately audited. |
| `server` | `qwen3.5-vl-8b-int4` | Server-side QC model | Larger server profile for backend visual reasoning when explicitly configured. |

These are product defaults, not a Qwen ecosystem lock-in. Product services depend on provider abstraction, so mainstream LLM/VLM providers can be added through adapters.

Environment selection:

```bash
QC_VISION_RUNTIME_ENV=tablet_mnn
QC_VISION_RUNTIME_ENV=server
```

Unknown or unset `QC_VISION_RUNTIME_ENV` falls back to `server`.

Older edition switch remains in place:

```bash
QC_RUNTIME_EDITION=padLocal|server
```

The edge profile is tablet, not desktop. Do not use `desktop_pc_mnn` for this product path.

---

## Visual QC Foundation

The visual QC engine introduces:

```text
provider abstraction for Qwen3.5-VL and other adapters
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

The tablet MNN edge profile executes confirmed rules. It is not used for learning.

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

---

## License

See `LICENSE`.
