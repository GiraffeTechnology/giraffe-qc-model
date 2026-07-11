# Phase 1 Jetson Xavier NX test report

Statuses are strictly one of **measured pass**, **measured fail**, or
**not tested**. Mock-runner results are never presented as model inference.

## Functional results

| Test | Status | Measured evidence |
|---|---|---|
| USB camera open/read | measured pass | V4L2 frame read; 640x480 probe and 1280x720 benchmark frame |
| Camera -> inline JPEG -> HTTP -> per-point response | measured pass (mock runner) | HTTP 200; two per-point results; one-shot HTTP latency 24.45 ms |
| Attached-display OpenCV window | measured pass | GTK window created on `DISPLAY=:0`; capture-once completed |
| Empty detection points rejected | measured pass | HTTP 403 with explicit `invalid_request` validation detail |
| Bad signature rejected | measured pass | HTTP 403 `bad_signature` |
| Phase 1 pairing rejected over LAN | measured pass | MacBook LAN request returned HTTP 403 `loopback_only` |
| Real qc-model/VLM inference | measured fail | PR #51 contains only mock implementation; no real adapter/runtime exists |

## Test suites

- PR #51 targeted Jetson/API tests: 37 passed, 1 warning.
- Modified runner tests: 15 passed.
- Full repository suite: 1058 passed, 6 skipped, 1 environment failure in
  331.05 seconds. The only failure was `FileNotFoundError: alembic` because the
  first invocation used an absolute venv Python without adding the venv's `bin`
  directory to `PATH`. Re-running that exact migration test with the correct
  PATH passed in 29.12 seconds. This was a test-launch environment issue, not a
  source failure.

## Fixed-frame mock HTTP baseline

Same 1280x720 camera frame repeated 50 times:

| Metric | Result |
|---|---:|
| Requests | 50 |
| Failures | 0 |
| p50 | 12.713 ms |
| p95 | 18.110 ms |
| max | 23.339 ms |

These values measure HTTP/JPEG payload parsing, Pydantic contract validation,
HMAC verification and deterministic mock response only. They are not VLM
inference latency.

## Stability

| Test | Status | Measured evidence |
|---|---|---|
| Kill and automatic restart | measured pass | PID 24970 killed; systemd restarted as PID 25066; health returned HTTP 200 |
| Two-hour continuous HTTP load | measured pass (mock runner) | 7200.62 s, 6719 requests, 0 failures |
| Cold power-on to ready | not tested | requires controlled power cycle/system-level boot service |
| Camera unplug/replug behavior | not tested | pending after continuous load |

## Outstanding issues

1. Real Xavier NX model variant/runtime is absent from PR #51. Model feasibility,
   GPU inference latency, OOM behavior and thermal throttling remain unmeasured.
2. The installed unit is a systemd user service with `Linger=no`, not the PRD's
   required pre-login system service. System installation needs sudo authority.
3. PR #51 is unmerged; the Phase 1 fix should target its source branch.
4. `gh` CLI is absent on the Jetson, so the draft PR publish workflow is pending.

## Two-hour continuous-load result

One fixed 1280x720 frame was sent once per second through the signed HTTP
contract. The request payload included the JPEG and full inline detection-point
fixture each time.

| Metric | Measured result |
|---|---:|
| Duration | 7200.617 s |
| Requests | 6719 |
| HTTP failures | 0 |
| p50 | 8.554 ms |
| p95 | 15.902 ms |
| max | 21.320 ms |
| Maximum sampled temperature | 50.0 C |
| Maximum runner RSS | 50.4 MB |
| systemd restarts during load | 0 |

Ten-minute windows:

| Minute | Samples | p50 ms | p95 ms | max ms | max temp C | max GPU % | min available MB | max RSS MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-10 | 559 | 8.710 | 16.062 | 20.236 | 50.0 | 58.9 | 5712.5 | 50.4 |
| 10-20 | 559 | 8.823 | 15.903 | 21.320 | 50.0 | 60.0 | 5708.8 | 50.4 |
| 20-30 | 560 | 8.575 | 16.093 | 21.002 | 50.0 | 63.0 | 5710.5 | 50.4 |
| 30-40 | 559 | 8.533 | 15.628 | 18.748 | 50.0 | 64.6 | 5712.0 | 50.4 |
| 40-50 | 560 | 8.705 | 15.898 | 20.943 | 50.0 | 74.9 | 5709.9 | 50.4 |
| 50-60 | 559 | 8.505 | 15.604 | 20.750 | 50.0 | 60.8 | 5702.0 | 50.4 |
| 60-70 | 561 | 8.468 | 15.695 | 17.824 | 50.0 | 72.7 | 5700.9 | 50.4 |
| 70-80 | 560 | 8.359 | 15.340 | 18.470 | 50.0 | 58.9 | 5697.5 | 50.4 |
| 80-90 | 563 | 8.441 | 14.386 | 17.610 | 50.0 | 57.7 | 5426.1 | 50.4 |
| 90-100 | 559 | 8.470 | 16.175 | 19.769 | 50.0 | 68.8 | 5366.9 | 50.4 |
| 100-110 | 560 | 8.680 | 16.454 | 19.027 | 50.0 | 62.7 | 5376.6 | 50.4 |
| 110-120 | 559 | 8.684 | 16.017 | 18.630 | 50.0 | 85.7 | 5375.0 | 50.4 |

The p50 did not drift upward across the run and RSS stayed flat. The GPU sample
is whole-device load and must not be interpreted as VLM utilization: the runner
was mock-only and no model was loaded.
