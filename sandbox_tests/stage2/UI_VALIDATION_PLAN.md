# Stage 2 UI validation plan

All visual evidence is non-production simulation evidence. Local image fixtures
and simulated capture/CV states must display a visible `NON-PRODUCTION MOCK`
label wherever a user could otherwise mistake them for live hardware output.

Validate these UI cases after Q1 is resolved:

| Case | User-visible expectation | Required evidence |
|---|---|---|
| Simulator ready | UI identifies the selected Stage 2 method and external-drive-backed test session | screenshot plus state payload |
| Simulated capture | Selected fixture is visibly labeled as simulated; no camera-connected claim | screenshot plus fixture reference |
| CV success | Normalized image and CV evidence render without turning CV evidence into an autonomous final verdict | screenshot plus CV result payload |
| CV anomaly | Invalid/insufficient evidence produces review/reject presentation, never silent pass | screenshot plus fail-closed state |
| Simulator unavailable | Mount, permission, dependency, or simulator failure produces an explicit blocking error | screenshot plus error code |
| Refresh/retry | Recovery after a deliberately removed simulation dependency is visible and does not duplicate results | before/after screenshots plus event log |

UI checks complement the standalone CV module tests. They do not move inference or
UI responsibilities across the Pad/Jetson boundary and do not validate real camera,
Jetson GPU, power, thermal, or production-network behavior.
