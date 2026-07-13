# Probation — Service/HTTP API Contract

**Owner:** WS7 (`claude/ws7-probation-integration`). **Consumed by:** Account
A's WS3 probation screen (round 1) and WS7's own Pad-side `ws7b` follow-up
(after WS3 merges).

**Status:** `[PLANNED]` throughout. `src/qc_model/qualification/probation.py`
already implements the full service layer (`start_probation`,
`record_probation_job`, `evaluate_gate`, `disagreement_report`,
`pause_probation`, `resume_probation`, `edit_resets_probation`) with unit
tests, but **no router calls any of it** — there is no
`src/api/qc_probation_router.py` today, and nothing outside tests imports
this module. This doc defines the HTTP surface WS7 must build to make those
functions reachable from Studio (and later the Pad). Note this is a
*different* module from `src/api/qc_qualification_router.py` /
`src/qc_model/qualification/service.py`, which implements the separate L3
accuracy-gate/shadow-mode qualification flow (PR 27) — do not conflate the
two "qualification" concepts when wiring this in.

## 1. Design constraints (from `probation.py`, do not redesign)

- Probation is keyed by `(tenant_id, standard_revision_id)` — one row per
  revision, idempotent `start_probation`.
- `min_sample_size=30`, `agreement_threshold=0.90`, `recheck_interval=10` are
  the PRD defaults but are stored per-probation and configurable at
  `start_probation` call time — the router should accept overrides only if
  Studio actually exposes that as an admin control; if not, just use the
  defaults and don't add unused parameters.
- Status is one of `active | paused | qualified` (`PROBATION_ACTIVE`,
  `PROBATION_PAUSED`, `PROBATION_QUALIFIED`). A qualified probation cannot be
  paused/resumed (raises `InvalidProbationState`) and cannot record more jobs
  (raises `ProbationNotActive`) — these are the service's own invariants; the
  router should map them to `409`, not swallow or re-derive the check.
- `record_probation_job` is idempotent per `job_ref` within a probation
  (duplicate → `InvalidProbationJob`) — map to `409` or `422`, WS7's call,
  but be consistent.

## 2. Endpoints (`src/api/qc_probation_router.py`, prefix `/api/qc/probation`, tags `["qc-probation"]`)

Follows the existing router conventions in this codebase (see
`src/api/jetson_router.py`, `src/api/qc_qualification_router.py`): FastAPI
`APIRouter`, `Depends(get_db_dep)`, tenant_id as a query param defaulting to
`"default"`, domain exceptions mapped to HTTP status in the router (not
leaked as 500s).

| Method + path | Maps to | Notes |
|---|---|---|
| `GET /api/qc/probation/by-revision/{standard_revision_id}` | `get_probation_for_revision` + `evaluate_gate` | Primary read for Studio's probation screen. `404` if no probation exists yet for that revision (i.e. not yet published/installed — § 3 covers when one gets created). |
| `GET /api/qc/probation/{probation_id}` | `get_probation` + `evaluate_gate` | By id, for direct links. `404` → `ProbationNotFound`. |
| `GET /api/qc/probation/{probation_id}/disagreement-report` | `disagreement_report` | Full report per `probation.py` § "Disagreement report" — this **is** the UI payload (§ 4), no separate transform needed. |
| `POST /api/qc/probation/{probation_id}/pause` | `pause_probation` | `409` on `InvalidProbationState` (already qualified). |
| `POST /api/qc/probation/{probation_id}/resume` | `resume_probation` | Same `409` mapping. |

**Not exposed as a direct public endpoint:** `start_probation` and
`record_probation_job`. Both are triggered by other server-side code paths
(§ 3), not called directly by Studio or the Pad — this matches WS7's own
instruction ("call `start_probation()` automatically when a Bundle/inspector
transitions to Published/Installed", "call `record_probation_job()` ... from
the real result-submission path"). If WS7 finds a legitimate need for a
direct admin "force-start probation" action (e.g. re-running probation on a
standard that predates this feature), add it explicitly and document it here
in the same PR — don't leave it as an implicit side door.

## 3. Wiring triggers (the actual P0 gap — endpoints alone don't satisfy WS7)

1. **Auto-start on Publish/Install**: locate the Bundle/inspector state
   transition that marks a standard Published/Installed (Bundle publish path,
   likely `src/qc_model/authoring/` or the bundle service — WS7 to confirm
   exact call site since this doc doesn't own that code) and call
   `start_probation(db, standard_revision_id, tenant_id, sku_id=...)` there.
2. **Record on result submission**: the real Operator result-submission path
   (shared with WS4's Pad→Server flow and Jetson's evidence-not-verdict
   results) must call `record_probation_job(db, probation_id, ai_verdict,
   human_final_verdict, tenant_id, job_ref=<inspection job id>,
   point_disagreements=[...])` once a human final verdict is captured for a
   job worked against a standard currently on probation. **Shared-file risk
   with WS4** — per the Supplement, do not silently resolve a conflict here;
   if WS4's branch already touches this path, rebase onto it and summarize
   both sides' intent in the PR for a human decision.
3. **Progress reset on edit**: wherever Standard Authoring edits
   `expected_value`/`pass_criteria` (WS6's authoring flow) creates a new
   `standard_revision_id`, `edit_resets_probation(changed_fields)` tells you
   whether that happened — a new revision id naturally gets a fresh
   `start_probation` record at 0 (idempotent get-or-create), so this is more
   "confirm the new-revision-id plumbing already does the right thing" than
   new logic, but verify it explicitly rather than assuming.

## 4. Disagreement-report payload shape (reused by Studio UI, no new transform)

```jsonc
{
  "probation_id": "string",
  "standard_revision_id": "string",
  "status": "active | paused | qualified",
  "gate": {
    "jobs_recorded": 0, "agreements": 0, "agreement_rate": 0.0,
    "min_sample_size": 30, "agreement_threshold": 0.9, "recheck_interval": 10,
    "min_sample_met": false, "threshold_met": false, "is_check_due": false,
    "qualified": false
  },
  "disagreements": 0,
  "detection_points": [
    {"point_code": "string", "disagreement_count": 0, "examples": [
      {"job_ref": "string", "sequence_no": 0, "ai_verdict": "string", "human_final_verdict": "string"}
    ]}
  ],
  "jobs": [
    {"job_ref": "string", "sequence_no": 0, "ai_verdict": "string",
     "human_final_verdict": "string", "agreed": false, "points": []}
  ]
}
```

Per WS7's own instructions, Studio should reuse its existing conversational
display component for this, not build new chart/table UI from scratch.

## 5. 90%-agreement → solo transition

`record_probation_job`'s return already includes `qualified_now: bool` — the
router doesn't need extra logic here, but the **consumer** (wherever a Pad
decides whether a job on this standard needs mandatory human confirmation)
must check `GET /api/qc/probation/by-revision/{id}`'s `status`/`gate.qualified`
before deciding "solo Active Inspection" vs. "Probation, human confirmation
required." This is a WS4/WS7 coordination point, not resolved by this
contract alone — flag it explicitly in both PRs if the two sides land at
different times.
