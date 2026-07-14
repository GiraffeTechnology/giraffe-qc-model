# Running Merge Log — CI/Merge Owner (Claude Code A)

Per `CLAUDE_CODE_A_CI_BRIEF.md` §6: every merge is recorded here
(rebase → full CI green → merge → log entry). Older detail for the first wave
lives in `P0_REMEDIATION_MERGE_SUMMARY.md`.

| Date (UTC) | PR | Action | Gates on rebased head |
|---|---|---|---|
| 2026-07-13 | #54 | merged — Step 0 v1 contracts (docs-only) | docs-only |
| 2026-07-13 | #55 | merged — WS1 build repro | suite 1036✓, Android✓, lints✓ |
| 2026-07-13 | #57 | merged — WS5 Xavier runner (v1) | suite 1059✓, lints✓ |
| 2026-07-13 | #61 | merged — WS3 Pad Admin module | suite 1059✓, Android 217✓, lints✓ |
| 2026-07-13 | #58 | merged — WS4 Operator+Jetson (v1); WS3↔WS4 conflict human-adjudicated (pairing → AdminHome), recorded on PR | suite 1059✓, Android 253✓, lints✓ |
| 2026-07-13 | #59 | merged — WS6 Studio authoring wiring | suite 1072✓, lints✓ |
| 2026-07-13 | #60 | merged — WS7 probation wiring (base retargeted to main) | suite 1083✓, lints✓ |
| 2026-07-13 | #56 | merged — WS2 i18n (last of wave 1) | suite 1090✓, lints✓ |
| 2026-07-13 | #50 | closed — superseded by WS2 | — |
| 2026-07-13 | main | post-merge verification + full-system test report (`QC_MODEL_FULL_SYSTEM_TEST_2026-07-13.md`); comment-only fix for `auditNoCloudInference` false positive | suite 1090✓, Android 253✓ + audits✓, E2E 38/38✓ |
| 2026-07-13 | #53 | merged — Jetson runtime feasibility research (docs-only; Option C selection) | docs-only |
| 2026-07-13 | #51, #52 | closed — content carried into main by WS5 (verified) | — |
| 2026-07-13 | #32 | closed — outdated; superseded by current bundle/store/submit implementations (noted Pad-side Ed25519 verifier as a potential fresh work item) | — |
| 2026-07-14 | #62 | merged — **Step 0 v2 contracts** (cloud-inference-api, xavier-admin-runner-api, pad-health-state, probation-api v2; v1 contracts marked superseded). Docs-only; claims lint✓ | docs-only |

## Architecture v2 queue (CLAUDE_CODE_A_CI_BRIEF §3 — strict order)

1. ~~Step 0 v2 contracts~~ ✅ #62
2. WS1 (build repro deltas, if any) — Codex
3. WS5 (Xavier admin-side runner, MNN adapter)
4. WS3 (Pad Admin module deltas) — merging triggers ws6b/ws7b
5. WS4 (operator cloud pipeline) — rebase onto WS3+WS5; WS3↔WS4 and WS4↔WS7
   conflicts escalate to human, never silently resolved
6. WS6 / WS7 Studio-side — any time after WS1
7. WS2 (i18n) — last of the wave
8. ws6b → ws7b
9. Final i18n sweep PR
10. WS8 (OpenCV pre-analysis) — only after WS4+WS5 merged

## Standing CI jobs (CI doc §1 / brief §2 — all present on main)

- `tests.yml` — clean-env frozen full suite on every push/PR (no path filter).
- `android-pad-ci.yml` — committed-wrapper build, Gradle audit tasks
  (no-cloud-inference / no-mocks / MNN deps), 3× assemble+unit tests,
  SHA-keyed APK artifact; runs on PRs touching `apps/android-qc/`.
- `remediation-lints.yml` — mock-labeling lint (hard) + no-unverified-claims
  (soft) on every push/PR.
- `qc-closed-loop-gate.yml` — manual, hardware-required v2 integration gate;
  fails closed without human hardware attestation; never auto-runs.

## Open items (hardware / follow-up)

- v2 closed-loop proof + 10s SLO on real link + failover telemetry (gate above).
- JetPack reflash, real-device E2E runs (1 minimum / 5 full), Section 7
  re-verification, follow-up audit report — REJECT verdict stands until then.
- Studio-publish ↔ S3 bundle-store bridge (Codex, ws6b round candidate).
- Probation v2 audit gaps (actor persistence on pause/resume/final-decision)
  — flagged in probation-api v2, owned by WS7/WS7b.
