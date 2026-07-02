# Production Assisted Mode (PR 25)

L2 Production Assisted Mode lets a **ready** Training Pack be used in a real
factory-assisted QC workflow. The model produces a **recommended** disposition
and per-detection evidence; the **final** pass/reject/review decision is always a
human one and is recorded in an immutable audit trail.

> Mocked tests prove the workflow only, not production visual accuracy.
> Production Assisted Mode **requires a human final decision** — the system never
> auto-finalizes pass/reject.

## Flow

```
ready Training Pack (production_assisted readiness passes)
→ inspection session
→ evidence capture(s)
→ run: confirmed detection points only → recommended disposition + evidence
→ mandatory human final decision (identity required)
→ append-only audit trail (evidence packet + final decision)
```

## Hard rules

- A session can only start when `evaluate_readiness(..., target_mode="production_assisted")`
  returns `production_assisted_allowed = True`.
- A run **fails closed** if the configured inspection provider is not
  production-eligible (mock / fake / stub / skeleton / deterministic / test).
  The default provider is the non-production mock (L0 only).
- A run records only *recommended* dispositions
  (`pass_recommended` | `reject_recommended` | `review_required` |
  `capture_retry_required` | `measurement_required`). It never finalizes.
- Physical-measurement detection points return `measurement_required` — never an
  AI pass.
- A recommended pass with **missing required evidence** is downgraded to
  `review_required`.
- Every `ProductionDetectionResult` links to `training_pack_id`,
  `confirmed_visual_rule_id` / `visual_rule_memory_id`, `detection_point_code`,
  source image, capture metadata, evidence regions, provider, model,
  prompt/schema version, confidence, uncertainty, and review conditions.
- The **only** finalization is `HumanFinalDecision`, which requires an operator/
  supervisor identity and is append-only (no update/delete API).

## API (tenant-scoped)

```
POST /api/qc/production/inspection-sessions
GET  /api/qc/production/inspection-sessions/{session_id}
POST /api/qc/production/inspection-sessions/{session_id}/captures
POST /api/qc/production/inspection-sessions/{session_id}/run
GET  /api/qc/production/inspection-runs/{run_id}
GET  /api/qc/production/inspection-runs/{run_id}/evidence
POST /api/qc/production/inspection-runs/{run_id}/final-decision
```

- Create session on a non-ready pack → `409`.
- Cross-tenant pack → `404`.
- Run with a non-production-eligible provider → `422`.
- Final decision without an identity → `422`.

## UI

`/admin/qc-model/production` and `/admin/qc-model/production/sessions/{session_id}`
show the selected SKU/station/Training Pack, captures, per-detection-point
recommendations with evidence/uncertainty/review reasons, and the human
final-decision controls + audit log.

## Provider

`ProductionInspectionProvider` (`src/qc_model/production/provider.py`) is the
abstraction. This PR ships the abstraction + a non-production mock (L0) + the
production-eligibility gate. The **real** server-side VLM provider
(`qwen3.5-vl-8b-int4`) is integrated in PR 26; production learning never runs on
`tablet_mnn`.

## Migration

`alembic/versions/013_qc_production_assisted.py` adds the six production tables.
Verified `up → down → up` clean. Evidence packets and final decisions are
append-only audit tables.

## Out of scope (later PRs)

- Real VLM provider integration (PR 26).
- Qualification harness / shadow mode / accuracy gate → L3 controlled active
  (PR 27).
- False-pass incident response & requalification (PR 28).
