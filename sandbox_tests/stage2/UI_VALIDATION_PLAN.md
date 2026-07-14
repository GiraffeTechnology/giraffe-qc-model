# Stage 2 UI validation plan

All visual evidence is non-production simulation evidence. Local image fixtures
and simulated capture/CV states must display a visible `NON-PRODUCTION MOCK`
label wherever a user could otherwise mistake them for live hardware output.

The 2026-07-15 user amendment adds a Mac-attached USB camera as a Stage 2
simulated-capture source. This amendment supersedes the source PRD's Stage 2
camera exclusion only for the Mac host; real Jetson camera integration remains
strictly Stage 3.

Validate these product UI cases after Q1 is resolved:

| Case | User-visible expectation | Required evidence |
|---|---|---|
| Role entry | Welcome page exposes working Administrator and Operator branches | Chrome navigation evidence for both branches |
| Bilingual flow | Welcome, logins, Operator workspace, inspection and report switch between English and Chinese at any time | DOM/screenshot evidence in both languages |
| Real job control | Operator searches an executable SKU and creates a persisted qc-model inspection job | UI evidence plus tenant-scoped API/DB assertion |
| Mac USB camera | Chrome enumerates the connected camera, renders live preview, captures a frame and binds it to the current job as `mac_usb_camera` | camera label, screenshot and persisted media record |
| Evidence gate | Submitting checkpoints without attached evidence is blocked | fail-closed UI/API evidence |
| Finalizer/report | Exact checkpoint set is persisted atomically; deterministic finalizer runs; report page reloads persisted verdict | UI evidence plus final report payload |

The following test-only surface remains supplemental for simulator state
presentation and does not satisfy real qc-model control by itself:

| Case | User-visible expectation | Required evidence |
|---|---|---|
| Simulator ready | UI identifies the selected Stage 2 method and external-drive-backed test session | screenshot plus state payload |
| Simulated capture | Selected fixture is visibly labeled as simulated; no camera-connected claim | screenshot plus fixture reference |
| CV success | Normalized image and CV evidence render without turning CV evidence into an autonomous final verdict | screenshot plus CV result payload |
| CV anomaly | Invalid/insufficient evidence produces review/reject presentation, never silent pass | screenshot plus fail-closed state |
| Simulator unavailable | Mount, permission, dependency, or simulator failure produces an explicit blocking error | screenshot plus error code |
| Refresh/retry | Recovery after a deliberately removed simulation dependency is visible and does not duplicate results | before/after screenshots plus event log |

Acceptance execution uses desktop Chrome to render and interact with the test-only
Pad-facing validation surface. The CV payload shown by that UI comes from the
separately verified QEMU aarch64 probe; Chrome is not represented as the Jetson
simulator. The earlier Android emulator capture remains supplemental evidence and
does not satisfy the Chrome acceptance requirement by itself.

Every screenshot must visibly include `NON-PRODUCTION MOCK`, and the Chrome
manifest must record the browser validation build, state payload, screenshot
path, and pass/fail. Chrome console errors and warnings must be empty.

UI checks complement the standalone CV module tests. They do not move inference or
UI responsibilities across the Pad/Jetson boundary and do not validate Jetson GPU,
power, thermal, or production-network behavior. A Mac USB capture proves only
browser capture and qc-model evidence persistence; it is not Stage 3 hardware proof.
