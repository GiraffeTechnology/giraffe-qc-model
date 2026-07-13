# Phase 1 Jetson Xavier NX deployment record

## Source selection

PR #51 was not merged at deployment time, so the PR-required inference runner
baseline is commit `0ba441bce5d6a4e44ef012e08ca73bbb51371a9c` from branch
`claude/qc-model-pluggable-cv-3p0zzs`. The Jetson work branch is based directly
on that commit.

## Runtime

The existing Python 3.11 environment was reused:

```text
/home/giraffe/work/giraffe-qc-model/.conda311
```

The repository was installed editable with `pip install -e`. No JetPack,
kernel, bootloader, CUDA, cuDNN, TensorRT, or model selection was changed.

## Phase 1 HTTP/CV additions

- `JETSON_PHASE1_LOOPBACK_PAIRING=false` by default.
- When explicitly enabled, `POST /phase1/pair-loopback` accepts pairing only
  from `127.0.0.1` or `::1`; LAN callers receive HTTP 403.
- `scripts/jetson_phase1_cv.py` uses the JetPack system Python/OpenCV to show
  live USB-camera video, capture on Space, inline JPEG, sign, call `/infer` over
  HTTP, and overlay per-point results.
- `scripts/jetson_phase1_fixture.json` is the local, inline-complete detection
  point fixture.
- `scripts/jetson_phase1_benchmark.py` repeats one fixed captured frame and
  records HTTP latency plus real temperature/GPU/memory/RSS measurements.

## systemd service

Installed as a user unit because system-level installation requires sudo
credentials that were not available:

```text
/home/giraffe/.config/systemd/user/giraffe-qc-jetson-runner.service
```

The unit is enabled, binds `0.0.0.0:8600`, restarts always after 3 seconds, and
logs to the user journal. The active graphical user session starts the unit.
`loginctl show-user giraffe -p Linger` reported `Linger=no`; therefore this is
not equivalent to a system unit that starts before login. This limitation is
reported, not hidden.

Installed unit contents:

```ini
[Unit]
Description=Giraffe qc-model Jetson Phase 1 runner
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/giraffe/work/giraffe-qc-model
Environment=JETSON_MOCK_MODE=true
Environment=JETSON_PHASE1_LOOPBACK_PAIRING=true
Environment=JETSON_BIND_HOST=0.0.0.0
Environment=JETSON_BIND_PORT=8600
ExecStart=/home/giraffe/work/giraffe-qc-model/.conda311/bin/python -m jetson_runner.app.main
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
```

`journalctl --user-unit giraffe-qc-jetson-runner.service` returned request logs,
confirming that service stdout/stderr is captured by journald.

## Important runtime limitation

PR #51 implements only deterministic mock inference. `JETSON_MOCK_MODE=false`
does not select or load a real VLM adapter; `jetson_runner/requirements.txt`
also explicitly omits a Xavier VLM runtime. Consequently this deployment can
validate the camera, HTTP contract, service lifecycle and resource behavior,
but cannot produce a real qc-model/VLM feasibility or latency result. No model
was substituted because the PRD forbids autonomous model selection changes.
