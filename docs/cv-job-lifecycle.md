# CV Job Lifecycle

A CV job represents one unit of computer-vision work against a source image.

## Happy path

```
pending → queued → leased → running → uploading_result → completed
```

1. **pending** — created by `POST /api/cv/jobs` (or auto-created by a live
   capture). Not yet dispatched.
2. **queued** — ready for assignment. If a capable online edge device exists the
   job stays queued for that device to *pull*; otherwise it is dispatched to CPU
   fallback (or escalated) immediately.
3. **leased** — a device pulled the job via `POST /api/edge-cv/jobs/next` and
   holds a time-bounded lease (`EDGE_CV_JOB_LEASE_SECONDS`, default 60s).
4. **running** — device called `POST /api/edge-cv/jobs/:id/start`.
5. **uploading_result** — device is uploading the structured result + evidence.
6. **completed** — result validated and persisted.

Every transition writes a `cv_job_events` row.

## Lease expiration (hot-unplug recovery)

A periodic sweep (`expire_leases`) finds jobs in `leased`/`running`/
`uploading_result` whose `lease_expires_at` has passed. For each:

1. write a `lease_expired` event;
2. release the device's active-job slot;
3. clear the assignment/lease;
4. increment `retry_count`;
5. if `retry_count ≤ max_retries` → `retry_scheduled → queued` (re-dispatch,
   using CPU fallback when no device is available);
   else → `manual_review_required`.

The lease deliberately survives a *brief* disconnect (network jitter): a job is
only recovered once the lease actually expires, not the instant a heartbeat is
missed.

## Retry behavior

```
EDGE_CV_MAX_RETRIES=2   # default; per-job override via max_retries
```

- **Transient failure** (agent `fail` with a non-permanent code, or lease
  expiry): retried within the budget.
- **Permanent failure** (`model_hash_mismatch`, `invalid_result_schema`,
  `model_missing`, `unsupported_task`): not retried — goes straight to review.
- **Budget exhausted:** `manual_review_required`.

## manual_review_required

The QC-safe terminal state. QC must never silently fail, so an exhausted /
permanently-failed / bad-payload job is surfaced for a human rather than marked
`failed` and forgotten. (A workflow that prefers hard failure can treat this as
`failed` downstream.)

## CPU fallback

When no capable edge device is online and `EDGE_CV_CPU_FALLBACK=true`, the job is
processed server-side by the CPU fallback runner:

```
queued → leased → running → uploading_result → completed
```

The result is deliberately lower-confidence and `pass_fail_hint =
needs_human_review`. With fallback disabled the job becomes
`manual_review_required` instead. Either way the workflow never blocks on a
missing Jetson.

## Cancellation

`POST /api/cv/jobs/:id/cancel` moves a non-terminal job to `cancelled` and
releases any held device slot.
