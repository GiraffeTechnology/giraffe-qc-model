# Jetson Runtime Readiness & Headless Operation

## Readiness states (§5)

The Pad is the only operator-facing window into a headless Jetson. It shows one
readiness state, resolved by `src/qc_model/jetson/service.resolve_readiness`:

```
no_sku_selected  →  no_standard_installed  →  jetson_unreachable
                                           →  jetson_connecting  →  jetson_ready
```

| State | Label | Can submit? |
|---|---|---|
| `no_sku_selected` | No SKU selected | no |
| `no_standard_installed` | No standard installed | no |
| `jetson_unreachable` | Jetson unreachable — offline mode | **no (fail-closed)** |
| `jetson_connecting` | Jetson connecting… | no |
| `jetson_ready` | Jetson connected & ready | **yes** |

**Fail-closed rule:** if the Jetson is unreachable the operator cannot submit an
inspection — the Pad must never fabricate a verdict or silently fall back to
another model. Only `jetson_ready` permits submission.

## Headless operation (§6)

Production Jetsons have **no display, keyboard, or mouse**. Implications:

1. **All status on the Pad.** Health (service up/down, model loaded,
   temperature/throttling, disk, last inference latency) is collected by the
   runner (`jetson_runner/app/health.py`), relayed by the Pad, and stored via
   `POST /api/qc/jetson/runners/{id}/health` for display. An operator never
   plugs in a monitor to know what's wrong.
2. **Auto-starting service.** The runner starts on boot (systemd), restarts on
   crash, needs no interactive login; power-cycle is a valid recovery. Example
   unit:

   ```ini
   [Unit]
   Description=Giraffe qc-model Jetson runner
   After=network-online.target
   [Service]
   ExecStart=/usr/bin/python3 -m jetson_runner.app.main
   Restart=always
   RestartSec=3
   [Install]
   WantedBy=multi-user.target
   ```
3. **Headless provisioning.** Flash/setup happens off-site; first-boot pairing
   completes via the Pad-side flow alone — no HDMI step anywhere in the runbook.
4. **Remote diagnostics (engineers only).** SSH over LAN, key-based, disabled by
   default and enabled per-device by config. Logs are pullable by the Pad so
   routine triage needs no SSH.
5. **Status LED (optional).** A GPIO LED for booting / ready / error
   (`JETSON_STATUS_LED=true`) helps floor staff without a screen. Not a blocker.

## Security (§7)

- The inference endpoint is **LAN-only**, never internet-exposed.
- The Jetson accepts requests **only from its paired Pad** (fail-closed);
  everything else is rejected. See `docs/jetson-headless-pairing.md`.

## Running the mock runner (no hardware)

```bash
cd jetson_runner
pip install -r requirements.txt
JETSON_MOCK_MODE=true python -m jetson_runner.app.main   # LAN endpoint on :8600
```

The mock runner and Pad client (`jetson_runner/app/pad_client.py`) let CI
exercise pairing + signed inference end-to-end without a Xavier NX. See
`jetson_runner/README.md`.
