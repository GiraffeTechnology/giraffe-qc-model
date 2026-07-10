# Jetson Xavier NX qc-model Runner (headless, mock-capable)

Runs qc-model VLM **inference** on images the Pad sends, and returns per-detection
-point evidence. Headless (no display/keyboard/mouse), LAN-only, paired 1:1 to a
single Pad. Mock mode needs no GPU/Xavier, so CI exercises the whole flow.

This is the **inference** stage; the **CV** stage (candidate capture/framing) is
the Jetson Nano (`edge_cv_agent/`) or the Pad. See
`docs/jetson-xavier-nx-inference.md`.

## Run (mock mode)

```bash
pip install -r requirements.txt
JETSON_MOCK_MODE=true python -m jetson_runner.app.main   # LAN endpoint on :8600
```

Endpoints: `GET /health`, `POST /infer` (`{pad_device_id, signature, request}`).

## Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `JETSON_DEVICE_ID` | generated | Stable device id (from provisioning). |
| `JETSON_MOCK_MODE` | `true` | Mock VLM + mock health (no hardware). |
| `JETSON_PAIRING_WINDOW_SECONDS` | `120` | Wi-Fi pairing-window length. |
| `JETSON_BIND_HOST` / `JETSON_BIND_PORT` | `0.0.0.0` / `8600` | LAN-only bind. |
| `JETSON_STATUS_LED` | `false` | Enable GPIO status LED (booting/ready/error). |

## Layout

```
jetson_runner/
  app/
    config.py           # env config
    identity.py         # provisioning identity + chassis fingerprint
    signing.py          # per-pair request signing (HMAC; mTLS in prod)
    pairing_agent.py    # headless USB + Wi-Fi(window+fingerprint) pairing, 1:1, fail-closed
    inference_server.py # mock qc-model inference over the §4 contract
    health.py           # health/readiness for the Pad (the only screen)
    pad_client.py       # MockPad — Pad-side pairing + signed requests (test/dev)
    main.py             # JetsonRunnerService + LAN HTTP entrypoint
  tests/                # pairing + inference unit tests
```

## Security / fail-closed properties

- Accepts inference only from its **one** current paired Pad; unpaired/unknown
  callers and bad/tampered signatures are rejected.
- Re-pairing to a new Pad drops the old binding immediately — **no grace period**.
- Pairing never requires the Server (floor first, sync later).
- Endpoint is LAN-only; never internet-exposed.

Pairing details: `docs/jetson-headless-pairing.md`. Readiness / headless ops:
`docs/jetson-runtime-readiness.md`.
