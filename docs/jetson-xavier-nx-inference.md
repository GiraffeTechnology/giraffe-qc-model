# Jetson Xavier NX — qc-model Inference Runner

This is the **inference** stage of the QC production line. It is distinct from
the Jetson **Nano 2GB** Edge-CV work (`docs/edge-cv-architecture.md`): the Nano
(or the Pad) is the **CV front-end** that produces a candidate frame; the Xavier
NX **runs qc-model VLM inference** on that frame and returns structured evidence.

## One production line

```
CV producer                         inference                verdict
────────────                        ──────────               ───────
Jetson Nano 2GB (auto-lock capture)  ─┐
   or                                 ├─▶  captured frame ─▶  Jetson Xavier NX ─▶ Pad ─▶ Server (S4)
Pad (local CV framing)              ─┘        + spec           qc-model VLM       displays   recomputes
```

Both the Nano and the Pad play the "CV" role and are interchangeable front-ends;
the Xavier NX has exactly one job: **run qc-model inference** on images the Pad
sends and return a per-detection-point verdict + confidence + evidence. It does
**not** watch live video or auto-capture (that's the CV front-end's job), does
not author/cache/version standards, and never talks to the Server directly.

## Role split (§1)

- **Pad (Android):** camera/UI, lightweight local CV framing (decide *when* to
  send a still), assembles the inference request (image + full detection-point
  spec), sends it to the paired Jetson over LAN, displays the verdict, handles
  Probation human-confirmation, submits to the Server outbox.
- **Jetson Xavier NX:** stateless-per-request qc-model inference only.

## Stateless per request — no bundle caching (§3)

The Jetson **never** installs or caches a standard bundle. Every request carries
the full detection-point spec inline (`expected_value`, `pass_criteria`,
`regions`) plus `standard_revision_id`/`bundle_version`. The Pad is the single
authority on which revision is active, so there is no Pad↔Jetson version skew and
no class of silently-wrong-verdict bugs.

## Contract (§4)

Shared, validated in `src/qc_model/jetson/contract.py`.

Request (Pad → Jetson, LAN):

```json
{ "job_id": "...", "standard_revision_id": "...", "bundle_version": "...",
  "image": "<captured frame>",
  "detection_points": [
    { "point_code": "...", "label": "...", "expected_value": "...",
      "pass_criteria": "...", "severity": "...",
      "regions": [ { "image_id": "...", "x":0,"y":0,"w":0,"h":0 } ] } ] }
```

Response (Jetson → Pad):

```json
{ "job_id": "...",
  "per_point_results": [
    { "point_code": "...", "result": "pass|fail|uncertain",
      "confidence": 0.0, "evidence": "..." } ] }
```

> **Jetson's response is evidence, not a verdict.** The Pad forwards it to the
> Server, which recomputes the authoritative overall pass/fail per the existing
> S4 rules (missing checkpoint ⇒ not pass; any failed checkpoint ⇒ not pass),
> evaluated against the revision actually used.

## Readiness states (§5) — fail-closed

`src/qc_model/jetson/service.resolve_readiness(...)` → one of:

| State | Meaning |
|---|---|
| `no_sku_selected` | No SKU chosen yet. |
| `no_standard_installed` | No standard for the SKU. |
| `jetson_unreachable` | **Inspection blocked** — no fabricated verdict, no fallback. |
| `jetson_connecting` | Reachable but model not loaded yet. |
| `jetson_ready` | Connected & ready — the only state that permits submission. |

`can_submit_inspection(state)` is true only for `jetson_ready`. If the Jetson is
unreachable the operator **cannot submit**, full stop.

## Server-side surface

The Jetson never calls the Server. The **Pad** relays, on sync:

- `POST /api/qc/jetson/runners` — record a provisioned runner (id + fingerprint).
- `POST /api/qc/jetson/bindings` — report a Pad↔Jetson pairing (1:1, re-pair
  fail-closed). See `docs/jetson-headless-pairing.md`.
- `POST /api/qc/jetson/runners/{id}/health` — relay Jetson health for the Pad UI.
- `POST /api/qc/jetson/readiness` — resolve the readiness state + submit gate.
- `POST /api/qc/jetson/inference/validate` — validate a request against the §4
  contract (helper; the Server is not in the inference path).

## Probation (§8)

No logic change: `qualification_evaluations` still records
`(ai_verdict, human_final_verdict, agreed)`; `ai_verdict` now originates from the
Jetson response instead of on-device MNN. No schema change.

## Components

| Piece | Location |
|---|---|
| Contract schemas | `src/qc_model/jetson/contract.py` |
| Server service (provision/bind/health/readiness) | `src/qc_model/jetson/service.py` |
| Fingerprint/identity helpers | `src/qc_model/jetson/identity.py` |
| DB models + migration | `src/db/qc_jetson_models.py`, `alembic/versions/019_jetson_runner.py` |
| HTTP API | `src/api/jetson_router.py` |
| Mock headless runner + Pad client | `jetson_runner/` |

See also `docs/jetson-headless-pairing.md` and `docs/jetson-runtime-readiness.md`.
