# Server Verdict Recomputation + Results (S4)

Safety-critical, security-sensitive. The server **never trusts** the Pad's
`overall_result` — it re-derives the authoritative verdict from the submitted
checkpoint results, evaluated against the `standard_revision_id` /
`bundle_version` the Pad actually used (never the latest revision).

## Pure core — `src/qc_model/verdict/recompute.py`

`recompute_verdict(submission, spec) -> ServerVerdict` is pure (no DB, no I/O),
so Session 7's security tests hit it directly.

Input shapes: `PadSubmission` (job_ref, standard_revision_id, bundle_version,
pad_overall_result, checkpoints) and `StandardRevisionSpec` (revision_id,
bundle_version, required_checkpoint_ids, critical_checkpoint_ids, known).

### Rules (§9.2) and precedence (highest wins)

| Condition | Server verdict |
|-----------|----------------|
| Unknown standard revision (`spec is None` or `known=False`) | `review_required` (fail-closed) |
| `bundle_version` mismatch vs the revision's expected version | `review_required` (fail-closed) |
| Any checkpoint result == `fail` | `fail` (critical noted separately) |
| Any required checkpoint missing | `review_required` |
| Any other non-passing checkpoint (`not_visible`, `low_confidence`, unknown value, …) | `review_required` |
| All required checkpoints `pass` | `pass` |

`fail` outranks `missing`/`review_required` (an observed defect is a hard fail),
but a `fail` can **never** be relaxed to a `pass`. A checkpoint counts as passing
only if its result is exactly `pass`.

The verdict records `agrees`, `differences` (`pad=… server=…`), and warnings —
notably `pad_claimed_pass_overridden` when the Pad asserted PASS but the server
did not.

## Persistence + service — `src/qc_model/verdict/service.py`

- `resolve_spec(...)` builds the spec from the exact revision the Pad used:
  required checkpoints = that revision's **active** detection points (by
  `point_code`); critical = those with `severity == "critical"`. Unknown revision
  → `None` → fail closed. `expected_bundle_version` (optional) enables the §9.5
  mismatch check for deployments that track the revision→bundle mapping.
- `ingest_submission(...)` persists the submission + checkpoints, recomputes, and
  stores `QCServerVerdict`.
- `record_human_decision(...)` records the human final decision **without**
  mutating the server verdict.

Models: `QCPadSubmission`, `QCSubmittedCheckpoint`, `QCServerVerdict`
(`src/db/qc_verdict_models.py`).

## Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/qc/results/submissions` | Pad submits a verdict → recompute + persist |
| GET | `/api/qc/results` | List recomputed results (tenant-scoped) |
| GET | `/api/qc/results/{submission_id}` | One result |
| POST | `/api/qc/results/{submission_id}/final-decision` | Record human final decision |
| GET | `/admin/results` | Results page: Pad vs server verdict, diffs/warnings, revision, bundle, human decision |

## Non-goals

Does not implement Pad-side submission (S6). This is the receiving/recompute/
display side only.
