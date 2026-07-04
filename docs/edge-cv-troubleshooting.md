# Edge CV Troubleshooting

| Symptom | Likely cause | What to check / do |
|---|---|---|
| **Device not registering** | `EDGE_CV_ENABLED=false`; wrong `EDGE_AGENT_SERVICE_URL`; service not reachable | `curl $SERVICE_URL/health`. Registration returns `503 edge_cv_disabled` when the feature is off. Confirm `device_name`/`device_type` in the payload. |
| **Heartbeat missing / device flips offline** | Agent not sending heartbeats, or interval > TTL | Ensure `EDGE_AGENT_HEARTBEAT_INTERVAL_SECONDS` (10) < `EDGE_CV_HEARTBEAT_TTL_SECONDS` (35). A `409 stale_or_unknown_session` means the session was superseded — re-register. |
| **Device stuck `busy`** | `current_active_jobs` not decremented (e.g. jobs never completed) | Busy clears when a job completes/fails or its lease expires. Run the lease sweep; check for jobs stuck in `leased`/`running`. |
| **Job stuck `leased`** | Agent pulled but never started/uploaded (crash/unplug) | The lease expires after `EDGE_CV_JOB_LEASE_SECONDS`; the sweep then requeues/falls back. Confirm the sweep is running. |
| **Lease expired unexpectedly** | Inference slower than the lease window | Increase `EDGE_CV_JOB_LEASE_SECONDS`, or lower per-device `max_concurrent_jobs`. |
| **Result rejected `409`** | Wrong device, stale session, expired lease, or unknown job | The uploading session must be the *active* one that holds the lease. After a reconnect, only the new session can upload. Job state is intentionally left unchanged. |
| **Result rejected `422`** | Bad payload — invalid `pass_fail_hint`, unknown `asset_type`, missing `result_type`/asset URI, or model-hash mismatch | Fix the payload. The job is moved to `manual_review_required` (never silently completed). |
| **Model hash mismatch** | Local model artifact differs from the manifest hash | Re-provision the correct model. This is a *permanent* error → no retry, straight to review. |
| **CPU fallback not running** | `EDGE_CV_CPU_FALLBACK=false`, or a capable device is (still) considered online | With fallback off, jobs with no device become `manual_review_required`. If a device is wrongly still `online`, run the offline sweep (heartbeat TTL). |
| **Mock mode not working** | `EDGE_AGENT_MOCK_MODE` unset/false, or missing runtime deps | Set `EDGE_AGENT_MOCK_MODE=true`. Mock mode needs only `httpx`; it never imports opencv/CUDA. Force a scenario with `EDGE_AGENT_FORCE_SCENARIO=timeout|memory_failure|…`. |
| **Capture upload `409`** | Stale/unknown session on `/api/edge-cv/captures/upload` | Re-register the agent; the capture must carry the current `session_id`. |
| **Capture saved but `qc_model_dispatch_status=failed`** | Downstream job creation failed | The photo/metadata is never lost; a retry sweep can re-dispatch. Inspect the `cv_captured_photos` row and service logs. |

## Useful checks

```bash
# device inventory + status
curl $SERVICE_URL/api/edge-cv/devices

# a single job's state + result ids
curl $SERVICE_URL/api/cv/jobs/<cv_job_id>
```

- All state transitions are recorded in `cv_job_events` — read them to see
  exactly what happened to a job.
- `EDGE_CV_ENABLED=false` disables the whole subsystem; the rest of the system
  is unaffected.
