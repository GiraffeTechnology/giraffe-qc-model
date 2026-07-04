# Edge CV Agent (Jetson Nano 2GB / mock runner)

A lightweight, pull-based agent that turns an edge device into a CV
co-processor for giraffe-qc-model. It is **hot-plug safe** and runs in **mock
mode** with no GPU/Jetson, so CI never needs real hardware.

```
register → heartbeat → pull job → (load/validate model) → run CV → upload result
```

## Run (mock mode)

```bash
pip install -r requirements.txt      # mock mode only needs httpx
export EDGE_AGENT_SERVICE_URL=http://localhost:8000
export EDGE_AGENT_MOCK_MODE=true
python -m edge_cv_agent.app.main
```

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `EDGE_AGENT_DEVICE_NAME` | `jetson-nano-2gb-lab-001` | Stable device name. |
| `EDGE_AGENT_DEVICE_TYPE` | `jetson_nano_2gb` | Device type. |
| `EDGE_AGENT_SERVICE_URL` | `http://localhost:8000` | Service base URL. |
| `EDGE_AGENT_TENANT_ID` | `default` | Tenant. |
| `EDGE_AGENT_POLL_INTERVAL_SECONDS` | `3` | Job poll interval. |
| `EDGE_AGENT_HEARTBEAT_INTERVAL_SECONDS` | `10` | Heartbeat interval (< service TTL). |
| `EDGE_AGENT_MAX_CONCURRENT_JOBS` | `1` | Reported capacity. |
| `EDGE_AGENT_MODEL_DIR` | `/opt/giraffe/models` | Model cache dir. |
| `EDGE_AGENT_OUTPUT_DIR` | `/opt/giraffe/cv_outputs` | CV output dir. |
| `EDGE_AGENT_MOCK_MODE` | `true` | Use the mock CV pipeline (no hardware). |
| `EDGE_AGENT_FORCE_SCENARIO` | — | Force a mock outcome (see below). |

## Mock scenarios

Driven by a job's `input_payload.mock_scenario` or `EDGE_AGENT_FORCE_SCENARIO`:
`success` (default), `timeout`, `memory_failure`, `model_missing`,
`model_hash_mismatch`, `partial_result`, `invalid_schema`. Failures are reported
to the service via the fail endpoint so the dispatcher can retry / fall back /
escalate.

## Layout

```
edge_cv_agent/
  app/
    config.py           # env config
    device_register.py  # registration payload + call
    heartbeat.py        # heartbeat payload + call
    health.py           # metrics collection (mock-friendly)
    job_client.py       # pull / start / fail
    model_loader.py     # model hash validation
    cv_pipeline.py      # mock CV runner + scenarios
    job_runner.py       # process one job end-to-end
    result_uploader.py  # structured result upload
    live_capture.py     # device-local auto-lock capture (debounce + dedup)
    main.py             # EdgeCVAgent orchestration
  tests/                # mock-runner + payload unit tests
```

The agent is transport-agnostic: `EdgeCVAgent(client, cfg)` accepts any client
with `.post(url, json=, headers=)` (httpx in production, FastAPI `TestClient`
in CI), which is how the hot-plug integration cycles drive it without a network.
