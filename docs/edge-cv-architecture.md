# Edge CV Architecture (Hot-Pluggable Co-Processor)

The Edge CV subsystem lets an optional edge device (e.g. an NVIDIA Jetson Nano
2GB) offload lightweight computer-vision work — image preprocessing, candidate
detection, crop/annotation generation — while the giraffe-qc-model **service
remains the single source of truth** for every business decision.

It is an **optional** feature. When `EDGE_CV_ENABLED=false` the rest of the
system behaves exactly as before.

## Core principles

- **Jetson is optional.** The service starts, runs, and processes CV jobs with
  no edge device present.
- **Jetson is hot-pluggable.** A device may be absent at startup, connected
  later, disconnected while idle or mid-job, rebooted, reconnected with the same
  identity, or replaced — all **without a service restart**. State is driven
  entirely by heartbeat TTL and job-lease expiration.
- **Service remains source of truth.** An edge device never writes to the DB. It
  only calls validated service APIs; the service validates device identity, job
  ownership, status transitions, model hash, result schema and asset references
  before persisting anything.
- **CPU fallback is mandatory.** When no capable edge device is online, the
  service processes the job on a CPU fallback runner (or escalates to manual
  review). No workflow ever freezes because Jetson is offline.
- **Pull-based acquisition.** The edge agent *pulls* jobs
  (`register → heartbeat → pull → process → upload`); the service never opens a
  connection to a device, so it never has to assume the device is reachable.
- **CV result is evidence, not a verdict.** `pass_fail_hint` is a hint only.
  Final QC judgement always stays in the QC/service layer with human confirmation.

## Components

```
Pad / IM / Email ──▶ giraffe service (workflow / API)
                         │
                         ▼
                  giraffe-qc-model DB
                         │
                         ▼
             CV Job Dispatcher  ── create · select device · lease · expire · fallback
                         ▲
                         │ pull-based
             Edge CV Device Agent (Jetson Nano 2GB / mock runner)
             register · heartbeat · pull job · run CV · upload result
```

| Layer | Module |
|---|---|
| DB models | `src/db/edge_cv_models.py` |
| Migration | `alembic/versions/018_edge_cv_hotplug.py` |
| Device service (register/heartbeat/TTL) | `src/qc_model/edge_cv/service.py` |
| Dispatcher (create/lease/expire) | `src/qc_model/edge_cv/dispatcher.py` |
| Result ingestion (validate/idempotent) | `src/qc_model/edge_cv/results.py` |
| CPU fallback runner | `src/qc_model/edge_cv/cpu_fallback.py` |
| Live-capture handoff | `src/qc_model/edge_cv/captures.py` |
| Device tokens | `src/qc_model/edge_cv/tokens.py` |
| HTTP API | `src/api/edge_cv_router.py` |
| Mock edge agent | `edge_cv_agent/` |

## Device state machine

```
unknown → registering → online ⇄ busy
                          online ⇄ degraded
online / busy / degraded → offline   (heartbeat TTL)
offline → registering                (reconnect)
online ⇄ maintenance                 (operator enable/disable)
online → error → registering / maintenance
```

- `online` — healthy, can accept jobs.
- `busy` — online but at `max_concurrent_jobs`.
- `degraded` — online but reporting resource pressure (low memory / high temp /
  full disk); still usable, deprioritised by the dispatcher.
- `offline` — missed heartbeat TTL or disconnected.
- `maintenance` — operator-disabled; no new jobs.
- `error` — unrecoverable runtime error reported by the agent.

## Job state machine

```
pending → queued → leased → running → uploading_result → completed
                     │          │
                     └──────────┴─▶ retry_scheduled → queued        (lease expiry / transient fail, under retry budget)
                                 └─▶ manual_review_required          (retry exhausted / permanent error / bad payload)
queued/leased/running → cancelled                                    (operator)
```

Every transition writes one `cv_job_events` row (full audit trail). For QC the
default terminal on exhaustion/permanent failure is `manual_review_required` —
QC must never silently fail.

See also: `docs/cv-job-lifecycle.md`, `docs/cv-result-schema.md`,
`docs/jetson-nano-2gb-hotplug.md`, `docs/edge-cv-troubleshooting.md`.
