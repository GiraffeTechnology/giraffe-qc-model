# QC Model — Full-System Test Report (2026-07-13, post first-wave merge)

Software-only whole-system test of `main` after the P0-remediation first wave
(see `P0_REMEDIATION_MERGE_SUMMARY.md`). Run in a clean cloud environment with
no physical Pad/Jetson hardware — hardware-dependent items remain open and are
listed at the end. No production-readiness claim is made by this report; it
records what was executed and observed (evidence: the commands and counts below).

## Layer 1 — Python suite, clean environment

```
rm -rf .venv && UV_CACHE_DIR=/tmp/uv-cache UV_PROJECT_ENVIRONMENT=.venv uv run --frozen pytest -q
→ 1090 passed, 6 skipped
```
All 6 skips are `RUN_QWEN_INTEGRATION=1` real-DashScope tests (external API
access required — explicit skip reason in the suite).

## Layer 2 — Android Pad app

```
./gradlew clean :app:assemblePadLocalDebug :app:testPadLocalDebugUnitTest \
          :app:verifyMnnNativeDeps :app:auditNoMocksInMainSrc :app:auditNoCloudInference
→ BUILD SUCCESSFUL — 253 unit tests, 0 failures
→ verifyMnnNativeDeps / auditNoMocksInMainSrc / auditNoCloudInference all pass
→ APK: giraffe-qc-padLocal-debug-<commit-sha>.apk (provenance-stamped filename)
```
Built with MNN `--ci-stubs` (as in CI); real native inference is not exercised
off-device.

## Layer 3 — Live-server HTTP end-to-end smoke (38/38 steps passed)

A real `uvicorn` server (APP_ENV=staging, real SESSION_SECRET, real Ed25519
bundle-signing key, migrated SQLite DB via `alembic upgrade head`) was driven
over HTTP through the full admin+operator loop:

1. Welcome page + brand icon (no emoji); zh-CN/ja page-chrome localization on
   pad/admin login and Studio (`<html lang>`, translated strings, no English残留).
2. Pad operator login (302 + session) and admin session login (303 + cookie);
   all five admin console pages render behind the fail-closed auth gate.
3. Studio SKU filter shows exactly the PRD 7-state lifecycle; legacy
   active/inactive/archived options absent.
4. Chat-first SKU create → multipart standard-photo upload (hardened
   validator) → photo serves back.
5. Chat intake extracts candidate checkpoints (staging uses the labeled
   NON-PRODUCTION MOCK extractor — wiring/data-flow validated, not real VLM) →
   category confirm creates an active standard revision with detection points.
6. WS6 region annotation route saves normalized `{image_id,x,y,w,h}` boxes;
   an out-of-bounds box is rejected 400 fail-closed.
7. Studio publish produces a signed L2 bundle; the signed `.tar.gz` archive
   downloads; **probation auto-starts on publish** (WS7) and is readable via
   `/api/qc/probation/by-revision/{rev}` (status `active`).
8. S3 bundle store: an Ed25519-signed manifest records via
   `POST /api/qc/bundles` (server verifies the signature); a tampered
   signature is rejected 400; signed download verifies.
9. Workstation registered and bundle assigned (assigned version reflected).
10. Verdict path: Pad-style submission → server recompute (`server=pass`,
    `agrees=true`) → human final decision recorded → **probation
    `jobs_recorded` incremented from the real verdict path** (WS7 wiring);
    probation pause/resume round-trips.
11. WS5 Jetson fleet endpoints: runner provisioned and listed.
12. Admin Results UI shows the submission.

Smoke driver: session-scratchpad `e2e_smoke.py` (not committed; steps listed
above are reproducible from the endpoints named).

## Layer 4 — Repo lints

`scripts/ci/mock_labeling_lint.py` and `scripts/ci/claims_lint.py` both pass
on `main`.

## Findings (fixed or recorded)

1. **Fixed on main** — `auditNoCloudInference` failed on WS4's
   `JetsonContract.kt` doc comment containing the substring "OpenAI-style"
   (comment-only false positive; no cloud call). Reworded. Note: this Gradle
   audit task is not currently a step in `android-pad-ci.yml`, which is why
   merge gates didn't catch it — consider adding it to CI.
2. **Recorded** — the Studio L2 publish store (`QCPublishBundle`,
   `/admin/studio/*`) and the S3 signed-bundle store (`/api/qc/bundles`,
   workstation assignment) are separate; publishing in Studio does **not**
   auto-record into the S3 store. Consequence: the Pad Administrator Bundles
   screen (WS3), which publishes via Studio but lists the S3 store, will show
   an empty list after publish until a bridge exists. Suggested follow-up
   (ws6b/ws7b round): record the published manifest into the S3 store as part
   of publish, or point the Pad list at the Studio store.
3. **Recorded** — an unset bundle-signing key surfaces as an unstructured 500
   on `/admin/studio/publish` (fail-closed is correct; the error should map to
   a structured 4xx/503 JSON body instead of a bare traceback).
4. **Recorded** — the labeled mock chat extractor recognizes English
   requirement patterns only (e.g. "pearl count 12"); equivalent Chinese input
   returns "no requirements identified". Real-extractor behavior TBD; worth a
   test once the production extractor lands.
5. Minor — Admin Results UI truncates submission ids to 8 chars (display
   choice, noted for anyone matching full ids).

## Still open (hardware / external)

- P0-4 real closed loop (real APK → Xavier NX → Server S4 → Admin Results):
  harness exists, **mock-only** in this environment — not closed.
- JetPack 5.1.x reflash; P0-10 real-device E2E runs (1 minimum / 5 for full
  acceptance); WS3 screen recordings; `RUN_QWEN_INTEGRATION=1` DashScope tests;
  real MNN native build (`-PwithMnnNative=true`) on device.
- Section 4 re-audit remains the gate for revisiting the REJECT verdict.
