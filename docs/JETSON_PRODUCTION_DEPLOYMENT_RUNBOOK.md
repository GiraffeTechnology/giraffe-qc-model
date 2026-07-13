# Jetson Xavier NX — Production Deployment Runbook (prep, 2026-07-13)

Preparation checklist for taking the Jetson inference stage to a production
line, following the human-approved runtime selection (**Option C**: reflash to
JetPack 5.1.x, 2B-class INT4 model, llama.cpp via `llama-server` HTTP — see
`JETSON_NX_RUNTIME_FEASIBILITY.md`). Software prerequisites verified in the
retest recorded in `QC_MODEL_FULL_SYSTEM_TEST_2026-07-13.md`; hardware steps
below are **human-executed on the device** and remain open until performed.
Nothing in this runbook claims the deployment is complete — the acceptance
gate at the end defines "done" (evidence: the P0-4 run artifacts it requires).

## 0. Current software state (verified in this repo, retest of `main`)

- Python suite clean-env: 1090 passed / 6 skipped (external-API skips only).
- Android Pad: `assemblePadLocalDebug` + 253 unit tests + all three audit
  tasks green; APK filename carries the commit SHA (provenance).
- Live-server HTTP E2E: 38/38 steps (admin loop, publish→probation, verdict
  loop, jetson fleet endpoints), with the labeled staging mock extractor.
- `jetson_runner` fail-closed guarantees in code + tests: unpaired/bad-signature
  `/infer` rejected; `JETSON_MOCK_MODE=true` under `APP_ENV=production` refuses
  to start (`MockModeNotAllowedInProduction`); mock defaults OFF in production.
- Real adapter present: `jetson_runner/app/adapters/llama_cpp_adapter.py`
  (Option C design — separate `llama-server` process over loopback HTTP).

## 1. Pre-reflash (human, on device — see feasibility doc §3.2)

- Back up: repo worktree, `qwen` model asset dir, `data/jetson/` SQLite,
  `artifacts/jetson_*` baselines, systemd unit files, Wi-Fi profiles, SSH keys.
- Record current `PHASE1_BASELINE.md`-style snapshot for before/after diff.

## 2. Reflash to JetPack 5.1.x (human; feasibility doc §3.3–3.4)

- SDK Manager on an x86 Ubuntu host; Force Recovery over USB; flash JetPack
  5.1.x (L4T r35, CUDA 11.4). Risks: bricking on QSPI interruption, no
  downgrade path, hours of downtime — schedule accordingly.
- After first boot: rebuild Python 3.11 venv, restore repo + Wi-Fi + SSH,
  re-collect the baseline (CUDA/cuDNN/TensorRT versions) — this is the
  "Phase 1.5" environment report that Task 2b adapter tuning waits on.

## 3. Model + llama-server (human, on device)

- Export/obtain the 2B-class INT4 model in GGUF; verify its sha256 and record
  it in the deployment record.
- Run `llama-server` (jetson-containers `dustynv/llama_cpp` r35.x image or
  native build) bound to `127.0.0.1:8080`.
- Memory watch: 8GB Xavier NX, ~5.6GB free at idle — measure real peak RSS
  with camera pipeline + runner service running (feasibility doc §5.3 flags
  the 8B option as likely infeasible; 2B is the chosen budget).

## 4. Jetson runner service configuration (production)

```bash
APP_ENV=production                     # mock refuses to start under this
# JETSON_MOCK_MODE must be UNSET (defaults false in production; =true aborts)
JETSON_DEVICE_ID=<stable device id>
JETSON_BIND_HOST=<LAN address>         # LAN-only; never internet-exposed
JETSON_BIND_PORT=8600
JETSON_LLAMA_SERVER_URL=http://127.0.0.1:8080
JETSON_LLAMA_MODEL_NAME=<deployed 2B model name>
JETSON_LLAMA_TIMEOUT_SECONDS=30
# JETSON_PHASE1_LOOPBACK_PAIRING must be UNSET/false in production
```
- Install as systemd unit; verify kill/restart recovery (Phase 1 procedure).
- Confirm `GET /health` reports `model_loaded=true` and non-mock values.

## 5. Server (qc-model) production configuration

```bash
APP_ENV=production                     # disables all labeled mock providers
SESSION_SECRET=<strong secret>         # startup refuses dev-default/empty
QC_BUNDLE_SIGNING_PRIVATE_KEY_PATH=<ed25519 pem>   # publish fails closed without it
QC_DB_URL=<production database URL>
```
- `alembic upgrade head` before first start (chain verified through 022).
- Note: publish with a missing signing key currently surfaces as an
  unstructured 500 (recorded finding) — provision the key before go-live.

## 6. Pad provisioning

- Install the provenance-stamped APK (`giraffe-qc-padLocal-debug-<sha>.apk`
  or the release flavor once signed); confirm the commit SHA in the startup
  `BuildProvenance` log matches the deployed `main` commit.
- Default runtime is Jetson-backed (`legacyMnnRuntimeEnabled=false`); do not
  enable the legacy MNN flag in production.
- Pair the Pad from **AdminHome → Jetson Pairing** (USB physical-proof or
  Wi-Fi window + chassis fingerprint). Re-pair replaces the old binding with
  no grace period — verify the old Pad's `/infer` is rejected afterward.
- Confirm fail-closed gate: with the Jetson unreachable, the operator submit
  action must be disabled (`jetson_unreachable`) — no fallback verdict.

## 7. Acceptance gate (defines "deployed" — per CI_AND_MERGE_INSTRUCTIONS §3–4)

1. **P0-4 real closed loop, ≥1 run**: real APK → signed LAN `/infer` on the
   Xavier NX (real llama.cpp inference, `isMock=false` surfaced in UI) → Pad
   displays + submits → Server S4 recompute → visible in Admin Results.
   Capture logs/screenshots/timing as reviewable artifacts.
2. **P0-10**: five consecutive real E2E runs for full acceptance (one run is
   only the minimum bar to re-open the verdict discussion).
3. Re-run the original audit's Section 7 verification commands and publish a
   follow-up audit report in the same format. Until that report exists, the
   REJECT verdict stands and no production-readiness claim is made.

## 8. Known open software items relevant to the line

- Studio-publish ↔ S3 bundle-store bridge (Pad admin Bundles list empty after
  Studio publish) — target ws6b round.
- ws6b/ws7b Pad-side hookups + final i18n sweep (WS6 region-editor strings,
  Android brand icon) — triggered, not yet delivered.
- Legacy SKU `status` value migration (lifecycle business-logic work).
