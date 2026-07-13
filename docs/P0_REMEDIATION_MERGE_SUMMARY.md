# P0 Remediation — First-Wave Merge Summary (2026-07-13)

Record of the CI & merge phase executed per `CI_AND_MERGE_INSTRUCTIONS.md` and the
Account A supplement. This document intentionally makes **no** production-readiness
or real-inference claims — final acceptance is gated on the Section 4 re-audit and
the open hardware items below.

## Merge order executed

Every branch was rebased onto the then-current `main` immediately before merge, and
merged only after all gates passed on the rebased head.

| # | PR | Workstream | Gate results on rebased head |
|---|---|---|---|
| 0 | #54 | Step 0 — API contracts (`docs/api-contracts/`) | docs-only |
| 1 | #55 | WS1 build repro | clean-env suite 1036 passed / 6 skipped; Android assemble + unit tests green; both lints pass |
| 2 | #57 | WS5 Xavier runner | clean-env suite 1059 passed; lints pass |
| 3 | #61 | WS3 Pad Administrator module | clean-env suite 1059 passed; Android assemble + 217 unit tests green; lints pass |
| 4 | #58 | WS4 Operator + Jetson | clean-env suite 1059 passed; Android assemble + 253 unit tests green; lints pass |
| 5 | #59 | WS6 Standard Authoring (Studio side) | clean-env suite 1072 passed; lints pass |
| 6 | #60 | WS7 Probation wiring (Studio side; base retargeted to `main` after WS6) | clean-env suite 1083 passed; lints pass |
| 7 | #56 | WS2 i18n (merged last of the wave) | clean-env suite 1090 passed; lints pass |

Post-merge verification on the final `main`: clean-env
`uv run --frozen pytest -q` → **1090 passed, 6 skipped** (skips are the
`RUN_QWEN_INTEGRATION=1` real-DashScope tests, which require external API access);
`./gradlew clean :app:assemblePadLocalDebug :app:testPadLocalDebugUnitTest` →
**BUILD SUCCESSFUL, 253 unit tests, 0 failures**. Draft PR #50 was closed as
superseded by WS2.

## Conflict resolutions (per CI doc §2, human-approved)

- **WS3 ↔ WS4** (`PadScreen.kt`, `MainActivity.kt`, `PadLanguageCatalog.kt`,
  deleted `AdministratorInfoScreen.kt`): reviewer-approved resolution — the info
  screen stays deleted (WS3's P0-0 requirement); WS4's Jetson pairing became an
  AdminHome grid destination returning to AdminHome; i18n catalogs took the union
  of both key sets; the admin health screen binds to the merged `MnnRuntime`
  abstraction so it reflects the Jetson-backed default runtime. No
  inspection/readiness business logic was altered. Recorded on PR #58.
- **WS4 ↔ WS7** result-submission overlap: did not materialize (WS7 hooks the
  server-side verdict path; WS4's changes were Pad-side). No decision needed.
- **WS2 ↔ WS6** (`admin_studio.html`): positional conflict only — WS6's
  region-editor `<template>` and WS2's i18n script block were both kept.

## P0-4 integration gate (CI doc §3) — NOT closed

- `tests/integration/test_jetson_pad_inference.py` exercises the full
  pairing → signed inference → evidence → server-sync slice, **but against
  `MockPad` with `mock_mode=True`** — an explicitly labeled mock. Per §3 this is
  recorded as a mock-only pass and is **not** represented as the P0-4 closure.
- The real closed loop (real APK → real Xavier NX inference → Pad submit →
  Server S4 recompute → Admin Results) **requires physical Pad + Jetson hardware
  that is not reachable from this environment**. Status: **open, hardware-required**.

## Open items requiring physical hardware / humans

1. **P0-4**: one real Pad → Jetson → Server closed-loop run with evidence capture
   (logs, screenshots, timing) — harness exists, run pending hardware.
2. **JetPack 5.1.x reflash** of the Xavier NX (WS5 scope, physical device access).
3. **P0-10**: real-device E2E runs — minimum one to reconsider the REJECT verdict,
   five consecutive for full acceptance (CI doc §4).
4. **WS3 screenshots/recording** of the Pad Administrator screens on a device with
   LAN backend access (flagged in PR #61).
5. **Section 4 re-audit**: re-run the original audit's Section 7 verification
   commands and publish a comparable follow-up audit report. Until that report
   exists, the REJECT verdict stands.

## Follow-up round (now unblocked)

- WS3 is merged to `main` — per the supplement this is Account B's trigger to open
  `ws6b` / `ws7b` (Pad-side hookups: region-write route consumption, probation
  screen wiring against the now-live `/api/qc/probation/*` surface).
- After ws6b/ws7b land: **final i18n sweep PR**, covering (at minimum) WS6's
  region-editor strings in `admin_studio.html`/`admin_studio.js` (currently
  English-only by design), any WS4 operator-screen strings added post-WS2, and the
  Android brand-icon swap deferred from WS2.
- Known deferred data item: legacy SKU `status` values (`active/inactive/archived`)
  still exist in stored rows; migration belongs to the lifecycle business-logic
  work (recorded in PR #56).
