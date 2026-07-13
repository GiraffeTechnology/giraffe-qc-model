# Jetson Xavier NX qc-model Runner (headless, mock-capable)

Runs qc-model VLM **inference** on images the Pad sends, and returns per-detection
-point evidence. Headless (no display/keyboard/mouse), LAN-only, paired 1:1 to a
single Pad. Mock mode needs no GPU/Xavier, so CI exercises the whole flow.

This is the **inference** stage; the **CV** stage (candidate capture/framing) is
the Jetson Nano (`edge_cv_agent/`) or the Pad. See
`docs/jetson-xavier-nx-inference.md` and the API contract at
`docs/api-contracts/jetson-runner-api.md`.

## Mock vs. real inference — read this before deploying

`JETSON_MOCK_MODE` selects between two adapters (`app/adapters/`):

- **`mock`** (`adapters/mock_adapter.py`) — deterministic, hash-derived
  results. No real image content is ever read. Every mock-served request logs
  `"MOCK INFERENCE — NOT REAL QC JUDGMENT"` at WARNING.
- **`llama_cpp`** (`adapters/llama_cpp_adapter.py`) — calls a local
  `llama-server` process over loopback HTTP. **This is an unvalidated
  scaffold**, not a certified inference path: it has never been run against
  real hardware or a real model (the JetPack 5.1.x reflash it depends on
  hasn't happened — see `JETSON_NX_RUNTIME_FEASIBILITY.md`). It exists so
  `JETSON_MOCK_MODE=false` has a real, complete, fail-closed code path to
  load, not so this repo can claim measured accuracy.

**`JETSON_MOCK_MODE=true` is refused outright when `APP_ENV=production`** —
`RunnerConfig` raises `MockModeNotAllowedInProduction` at construction, so a
misconfigured production deployment fails to start rather than silently
running mock. `mock_mode` defaults to `false` under `APP_ENV=production` and
`true` otherwise, so a real deployment needs no special mock-related config
beyond setting `APP_ENV=production`.

When the real adapter is selected but isn't ready (llama-server unreachable
or not answering `/health`), `POST /infer` is rejected with `503
runtime_not_ready` — it never falls through to mock or lets a bad call
through.

## Run (mock mode)

```bash
pip install -r requirements.txt
JETSON_MOCK_MODE=true APP_ENV=test python -m jetson_runner.app.main   # LAN endpoint on :8600
```

## Run (real adapter, once JetPack 5.1.x + llama-server are set up)

```bash
pip install -r requirements.txt   # installs httpx for the adapter's HTTP client
JETSON_MOCK_MODE=false \
JETSON_LLAMA_SERVER_URL=http://127.0.0.1:8080 \
JETSON_LLAMA_MODEL_NAME=qwen3.5-vl-2b-int4 \
python -m jetson_runner.app.main
```

`llama-server` itself is a separate process/service this does not manage —
see the feasibility doc for backend selection and setup, which is a Phase 1.5
device-side task, not something this repo installs.

## Endpoints

| Method + path | Purpose |
|---|---|
| `GET /health` | Health/readiness for the Pad (§6.1). Includes `mock: bool` so callers never have to infer it from other fields. |
| `POST /pair/usb` | Real LAN pairing, USB path. See the caveat in `docs/api-contracts/jetson-runner-api.md` §1.4 about what "USB path" currently does and doesn't guarantee at the network layer. |
| `POST /pair/wifi` | Real LAN pairing, Wi-Fi path — only inside an open pairing window, with a matching chassis fingerprint. |
| `POST /infer` | `{pad_device_id, signature, request}` — the §4 inference contract. |
| `POST /phase1/pair-loopback` | Test-only, disabled by default, loopback-restricted. Not for production pairing. |

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `JETSON_DEVICE_ID` | generated | Stable device id (from provisioning). |
| `JETSON_MOCK_MODE` | `false` under `APP_ENV=production`, else `true` | Selects the mock or llama_cpp adapter. Refused (raises) if `true` under `APP_ENV=production`. |
| `JETSON_PAIRING_WINDOW_SECONDS` | `120` | Wi-Fi pairing-window length. |
| `JETSON_BIND_HOST` / `JETSON_BIND_PORT` | `0.0.0.0` / `8600` | LAN-only bind. |
| `JETSON_STATUS_LED` | `false` | Enable GPIO status LED (booting/ready/error). |
| `JETSON_LLAMA_SERVER_URL` | `http://127.0.0.1:8080` | llama-server base URL (real adapter only). |
| `JETSON_LLAMA_MODEL_NAME` | `qwen3.5-vl-2b-int4` | Model name sent to llama-server. |
| `JETSON_LLAMA_TIMEOUT_SECONDS` | `30` | Per-call HTTP timeout to llama-server. |

## Layout

```
jetson_runner/
  app/
    config.py           # env config; production mock-mode lock
    identity.py         # provisioning identity + chassis fingerprint
    signing.py          # per-pair request signing (HMAC; mTLS in prod)
    pairing_agent.py    # headless USB + Wi-Fi(window+fingerprint) pairing, 1:1, fail-closed
    inference_server.py # mock qc-model inference core (used by adapters/mock_adapter.py)
    adapters/
      base.py            # InferenceAdapter interface (VisionLanguageModelProvider-style)
      mock_adapter.py     # wraps inference_server.py
      llama_cpp_adapter.py  # real adapter -- unvalidated scaffold, see caveat above
    health.py           # health/readiness for the Pad (the only screen)
    pad_client.py       # MockPad — Pad-side pairing + signed requests (test/dev)
    main.py             # JetsonRunnerService + LAN HTTP entrypoint (build_app/main)
  tests/                # pairing + inference + adapter + HTTP-layer unit tests
```

## Security / fail-closed properties

- Accepts inference only from its **one** current paired Pad; unpaired/unknown
  callers and bad/tampered signatures are rejected.
- Re-pairing to a new Pad drops the old binding immediately — **no grace period**.
- Pairing never requires the Server (floor first, sync later).
- Endpoint is LAN-only; never internet-exposed.
- A not-ready real backend fails closed (`503 runtime_not_ready`) instead of
  falling back to mock or letting a broken call through.
- Mock inference cannot be selected under `APP_ENV=production`.

Pairing details: `docs/jetson-headless-pairing.md`. Readiness / headless ops:
`docs/jetson-runtime-readiness.md`. Full API contract:
`docs/api-contracts/jetson-runner-api.md`.
