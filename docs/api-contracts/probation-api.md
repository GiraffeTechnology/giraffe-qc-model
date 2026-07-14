# Probation State, Agreement, and Qualification API Contract

**Contract version:** `2.0`

**Owner:** WS7 (`claude/ws7-probation-integration`)

**Consumers:** WS3 Pad Administrator probation screen and WS7b Pad hookup

**Status on `main`:** the service, read/report/pause/resume router, automatic
start on Studio Bundle publish, and human-final-decision recording hook exist.
WS3 now binds the live read/report/pause/resume surface on the Pad, including
in-flight mutation disabling and server-owned refresh. WS7b's remaining hookup
is separate from `qc_qualification_router.py` and the L3 accuracy-gate/shadow-
mode flow.

All `/api/qc/*` routes use the repository's authenticated admin/tenant gate.
Tenant identity comes from the authenticated principal; callers cannot widen
scope with a request `tenant_id`. Pad actions use the logged-in administrator
session. The current mutation handlers do not yet persist that principal on a
probation audit event; this required v2 audit hookup is called out below.

## 1. State and invariants

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
  (duplicate → `InvalidProbationJob`). The current internal hook ignores a
  duplicate because a real production job counts once.
- Every probation job requires a real server AI verdict and a real human final
  verdict. Missing human confirmation is not an agreement and cannot advance
  the counter.
- The agreement gate is evaluated at jobs 30, 40, 50, and so on. Meeting 90%
  between scheduled checks does not transition state early.
- `qualified` means mandatory human confirmation may stop for that exact
  standard revision. It does not rewrite historical jobs or qualify a newly
  created revision.

## 2. Endpoints

Follows the existing router conventions in this codebase (see
`src/api/jetson_router.py`, `src/api/qc_qualification_router.py`): FastAPI
`APIRouter`, `Depends(get_db_dep)`, tenant_id as a query param defaulting to
`"default"`, domain exceptions mapped to HTTP status in the router (not
leaked as 500s).

| Method and path | Status | Notes |
|---|---|---|
| `GET /api/qc/probation/by-revision/{standard_revision_id}` | `[EXISTS]` | Primary WS3 read. `404` before a revision has a probation record. |
| `GET /api/qc/probation/{probation_id}` | `[EXISTS]` | Direct lookup; tenant-scoped `404` when absent. |
| `GET /api/qc/probation/{probation_id}/disagreement-report` | `[EXISTS]` | Agreement summary plus auditable jobs and point disagreements. |
| `POST /api/qc/probation/{probation_id}/pause` | `[EXISTS, AUDIT GAP]` | Idempotent while paused; `409` after qualification. WS7b must persist the authenticated actor. |
| `POST /api/qc/probation/{probation_id}/resume` | `[EXISTS, AUDIT GAP]` | Returns to active; `409` after qualification. WS7b must persist the authenticated actor. |
| `POST /api/qc/results/{submission_id}/final-decision` | `[EXISTS, ACTOR GAP]` upstream event | Records the human verdict and advances active probation exactly once. It currently accepts caller-supplied `decided_by`; v2 must bind it to the authenticated principal. |

`start_probation` and `record_probation_job` are intentionally not public
endpoints. They run from trusted server transitions in §4. A client cannot
force-start probation or inject agreement rows.

Pause/resume currently require no body. The authenticated administrator is the
required actor; WS7b must add an append-only audit record for that identity. A
later optional reason may be added additively. The final-decision route must
derive `decided_by` from the authenticated principal (or reject a mismatched
legacy body field) before the actor gap can be considered closed.

## 3. Probation view

The two probation reads and pause/resume actions return:

```json
{
  "probation_id": "prob_01J2ABCDEF",
  "tenant_id": "tenant_hk",
  "sku_id": "sku_01J2SKU",
  "standard_revision_id": "rev_01J2STANDARD",
  "status": "active",
  "gate": {
    "jobs_recorded": 24,
    "agreements": 22,
    "agreement_rate": 0.9166666667,
    "min_sample_size": 30,
    "agreement_threshold": 0.9,
    "recheck_interval": 10,
    "min_sample_met": false,
    "threshold_met": true,
    "is_check_due": false,
    "qualified": false
  }
}
```

`status` is `active | paused | qualified`. WS3 derives presentation rules:

| Status | Human final verdict required? | Admin actions |
|---|---:|---|
| `active` | yes | pause, view report |
| `paused` | no production advancement | resume, view report |
| `qualified` | no | view report only |

The screen refreshes this resource after a final decision; a transition to
`qualified` is server-owned and must not be predicted from a client-side
floating-point calculation.

## 4. Server-owned transitions

1. **Publish/Install → active.** `publish_bundle()` calls idempotent
   `start_probation()` for the exact published `standard_revision_id`.
2. **Cloud result → S4.** WS4 sends real cloud point results through the outbox
   to `/api/qc/results/submissions`; S4 stores the authoritative server verdict.
   This does not advance probation yet.
3. **Human final decision → record.** The final-decision endpoint stores the
   human decision, then records `(server verdict, human verdict, agreed)` for an
   active probation using the inspection `job_ref`. Missing, paused, or already
   qualified probation is a no-op; duplicate `job_ref` is counted once.
4. **Scheduled gate → qualified.** At 30, 40, 50, ... jobs, the server changes
   `active` to `qualified` if agreement is at least the configured threshold.
5. **Progress reset on edit**: wherever Standard Authoring edits
   `expected_value`/`pass_criteria` (WS6's authoring flow) creates a new
   `standard_revision_id`, `edit_resets_probation(changed_fields)` tells you
   whether that happened — a new revision id naturally gets a fresh
   `start_probation` record at 0 (idempotent get-or-create), so this is more
   "confirm the new-revision-id plumbing already does the right thing" than
   new logic, but verify it explicitly rather than assuming.

## 5. Disagreement report

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

`jobs` are ordered by recorded sequence. `examples` and `points` contain only
recorded per-point human comparisons; the current overall-only final-decision
flow legitimately returns empty point arrays rather than inventing detail.

## 6. Errors and client behavior

- `401/403`: authentication/role/tenant failure; do not retry as another tenant.
- `404`: probation or result is absent in the authenticated tenant.
- `409`: pause/resume conflicts with a qualified state.
- `400` on final decision: invalid decision enum.

WS3 must disable pause/resume while a mutation is in flight, refresh from the
server on completion, and show failures without optimistic status changes.
Network failure never changes local counters or qualification state.

## 7. Compatibility

Additive fields are compatible. Changes to state values, cadence semantics,
agreement denominator, qualification threshold meaning, or server-owned
trigger points are breaking and require this file to change in the same PR.
