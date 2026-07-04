# Jetson Nano 2GB Hot-Plug Guide

How to run the edge agent, register a device, and unplug/replug safely — all in
mock mode, so **no real Jetson hardware is required** for development or CI.

## 1. Start the service

```bash
uv run uvicorn src.api.main:app --port 8000
# optional: seed the mock runner, Jetson profile, and mock model
uv run python scripts/seed_edge_cv_data.py
```

The service starts and is fully usable with **no** edge device present — CV jobs
fall back to the CPU runner.

## 2. Start the edge agent (mock mode)

```bash
cd edge_cv_agent
pip install -r requirements.txt        # mock mode only needs httpx

export EDGE_AGENT_SERVICE_URL=http://localhost:8000
export EDGE_AGENT_DEVICE_NAME=jetson-nano-2gb-lab-001
export EDGE_AGENT_DEVICE_TYPE=jetson_nano_2gb
export EDGE_AGENT_MOCK_MODE=true

python -m edge_cv_agent.app.main
```

The agent, in order: loads config → registers → stores `device_id` +
`session_id` + `auth_token` → sends heartbeats → polls for jobs → runs the (mock)
CV pipeline → uploads structured results → reports failures safely.

## 3. How registration works

Registration is gated by a shared **bootstrap secret**. Set
`EDGE_CV_REGISTRATION_SECRET` on the service and give each agent the same value
via `EDGE_AGENT_BOOTSTRAP_TOKEN`; the agent sends it as the
`X-Edge-CV-Bootstrap-Token` header. In production a missing/unset secret rejects
all registrations (`401`) unless you explicitly opt into
`EDGE_CV_ALLOW_INSECURE_REGISTRATION=true`; the test environment allows insecure
registration by default so the suite needs no secret.

`POST /api/edge-cv/devices/register` creates (or updates) the device row and
opens a **fresh session**. The response returns:

```json
{
  "device_id": "edge_dev_…",
  "session_id": "edge_sess_…",
  "auth_token": "…",              // signed device token — send as Bearer on every agent call
  "heartbeat_interval_seconds": 10,
  "job_poll_interval_seconds": 3
}
```

A returning device keeps its `device_id` but gets a **new** `session_id`; the
previous session is closed. Any job lease owned by the old session becomes stale
and can no longer upload a result (prevents partial results from corrupting
current state).

## 4. How heartbeat works

`POST /api/edge-cv/devices/heartbeat` (Bearer device token) refreshes the TTL,
records a metrics sample, and derives status:

- at `max_concurrent_jobs` → `busy`;
- low memory / high temperature / full disk → `degraded`;
- otherwise → `online`.

Config:

```
EDGE_CV_HEARTBEAT_INTERVAL_SECONDS=10
EDGE_CV_HEARTBEAT_TTL_SECONDS=35
```

If `now - last_heartbeat_at > TTL`, a periodic sweep marks the device `offline`
— **without any service restart**.

## 5. Unplug / replug safely

- **Unplug while idle:** heartbeats stop → after TTL the device is marked
  `offline` and its session is closed with reason `heartbeat_ttl`. New jobs go to
  another device or CPU fallback.
- **Unplug during a job:** the job keeps its lease until it expires (guards
  against brief network jitter). On expiry the job is requeued / fallback-run /
  escalated — never silently lost.
- **Replug / reboot:** the agent re-registers → new session, heartbeats resume,
  new jobs flow. Stale uploads from the old session are rejected.

## 6. Verify device state

```bash
curl http://localhost:8000/api/edge-cv/devices                 # list all
curl http://localhost:8000/api/edge-cv/devices/<device_id>     # one device
```

Put a device into / out of maintenance:

```bash
curl -X POST http://localhost:8000/api/edge-cv/devices/<id>/disable
curl -X POST http://localhost:8000/api/edge-cv/devices/<id>/enable
```

## 7. Run mock mode / tests

```bash
# service + integration cycles (mock hot-plug, unplug-during-job, fallback, …)
uv run pytest tests/test_edge_cv_devices.py tests/test_edge_cv_jobs.py \
              tests/test_edge_cv_captures.py \
              tests/integration/test_edge_cv_hotplug_cycles.py -v
# agent-side unit tests
uv run pytest edge_cv_agent/tests -v
```

Mock mode simulates successful inference, timeout, memory failure, model
missing, model-hash mismatch, partial result and invalid schema — driven by
`input_payload.mock_scenario` or `EDGE_AGENT_FORCE_SCENARIO`.

## Real Jetson notes (documented, not required for CI)

A real deployment swaps `EDGE_AGENT_MOCK_MODE=false` and provides a real CV
pipeline + `psutil`/`tegrastats` metrics in `edge_cv_agent/app/health.py` and
`cv_pipeline.py`. Nothing else changes: the same register/heartbeat/pull/upload
protocol and the same service-side validation apply.
