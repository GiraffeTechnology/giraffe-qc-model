# QC Standard Authoring Extension — Implementation Notes

Implements the admin-side PRD **"QC Standard Authoring Extension — Process Card
Input, Region Annotation, Probation Qualification"** and the direction set by the
**Digital QC Worker Skill Replication** supplement (Probation as digital-worker
apprenticeship; regions as visual grounding; process cards as skill source
material).

Scope is admin-side only. No change to Pad QC inference logic; no change to the
server-side verdict recomputation logic (S4) — Probation only gates *which
revisions may run without mandatory human confirmation*.

---

## 1. Process card (工艺卡) input — §1

Process card is a recognized authoring source **format**, not a new payload
shape. The concrete document is classified and routed, honestly, without
guessing at unreadable content.

- `QCSourceType.PROCESS_CARD` (`process_card`) added to
  `src/qc_model/ingestion/types.py`.
- `src/qc_model/ingestion/process_card.py` classifies an upload and returns a
  routing plan:

  | Format | Path | Notes |
  |--------|------|-------|
  | Electronic doc (PDF/Word/Excel/text) | `direct_text` | text extractable — feeds §5.4 extraction directly, no OCR |
  | Photo / scan (JPEG/PNG/TIFF/…) | `vision_ocr` | needs a vision OCR pass first |
  | CAD export (DWG/DXF/STEP/IGES/…) | `cad_render` | **best-effort, risk-flagged** — render to image then OCR; verify the toolchain before claiming support |
  | Unknown | `unsupported` | refuses to guess |

  `has_inline_text=True` always routes `direct_text` (upstream already recovered
  the text). Filename extension wins over mime type.

**Deferred / best-effort (open item §6):** the actual OCR and CAD-render
toolchains are not wired here — the module returns the plan and the
`vision_ocr` / `cad_render` requirement rather than performing it. CAD support
must not be claimed until the toolchain is verified (PRD §0, §6, acceptance §5).

## 2. Region annotation — §2

A detection point can be spatially grounded on the SKU's standard photos with
**zero, one, or many** normalized bounding boxes.

- Data model: `QCDetectionPoint.regions_json` — a JSON list of
  `{image_id, x, y, w, h}` (0–1 coords, top-left origin, resolution-independent).
  Migration `019_detection_point_regions`.
- Validation + persistence: `src/qc_model/studio/regions.py`
  (`normalize_regions`, `set_detection_point_regions`). Fail-closed: coords must
  be in `[0,1]`, the box must stay inside the image and have positive area,
  `image_id` must reference a standard photo of the same SKU/tenant, and only
  the five bounding-box keys are accepted (freehand/polygon out of scope).
- Regions surface in the studio detection-point view (`_dp_view`) and in the
  signed publish bundle manifest, so they travel with a mature skill package
  (Supplement §6).
- Contracts updated: `contracts/schemas/detection_point.schema.json` and the
  OpenAPI `DetectionPoint` gain an optional `regions` array + `Region` schema.
  Regions are optional — a point with no region is still valid (§0).

**Deferred:** the canvas draw/overlay UI in Admin Studio consumes these
fields; this change delivers the data model, validation, and contract that the
overlay builds on.

## 3. Standard Probation (试用期) — §3

A newly installed standard runs **real** production jobs under mandatory human
confirmation until it proves it can run solo. Tracked per
`standard_revision_id`, never as a synthetic test set.

- Lifecycle: `PROBATION` state inserted between `INSTALLED_ON_PAD` and
  `ACTIVE_INSPECTION` in `contracts/state_model.py`, both Kotlin mirrors,
  `en.json`, `CONTRACTS.md`, and OpenAPI. A newly installed standard transitions
  `installed_on_pad → probation`; it graduates `probation → active_inspection`
  only through the gate (or `→ needs_requalification` on a false-pass incident).
- Data model: `QCProbation` (counters + thresholds per revision) and
  `QCProbationJob` (one row per real job: `ai_verdict`, `human_final_verdict`,
  `agreed`, per-point disagreements). Migration `020_standard_probation`.
- Service: `src/qc_model/qualification/probation.py`.

### Mechanics (§3.2 / §3.3)

- `record_probation_job` records each `(ai, human)` pair, computes `agreed`, and
  updates counters. It rejects recording when paused or already qualified, and
  dedupes by `job_ref`.
- **Minimum sample size 30.** `evaluate_gate` never reports `qualified` below 30
  jobs — even at 100% agreement.
- **Gate:** from job 30 onward, if agreement ≥ 90% at a scheduled check the
  standard auto-transitions to `qualified`. Checks fire at 30, then every +10
  (40, 50, …); between checks no transition happens.
- `disagreement_report` returns per-detection-point divergences (AI vs. human),
  ranked most-divergent first — plain structured data for the existing
  conversational display (no new UI).
- `pause_probation` / `resume_probation` — the admin can pause at any time to
  edit in Studio; counters are preserved across pause/resume.

### Reset rule for edits (§3.4)

`edit_resets_probation(changed_fields)`:

| Field edited | Behavior |
|--------------|----------|
| `description` / regions | Preserved, no reset |
| `expected_value` | **Reset** — new revision, counter restarts at 0 |
| `pass_criteria` | **Reset** — new revision, counter restarts at 0 |

Because probation is keyed on `standard_revision_id`, a reset edit is realized
by the caller creating a new revision and calling `start_probation` on it —
which naturally starts a fresh record at 0 while the prior revision's record is
left intact.

Thresholds (`min_sample_size`, `agreement_threshold`, `recheck_interval`) are
per-record and deployment-configurable, but the *concept* is mandatory
(Supplement §5).

---

## Open items (not blocking; from PRD §6)

- Spot-check sampling rate once a standard reaches `Active Inspection` (undefined
  in PRD).
- CAD process-card toolchain feasibility — verify before claiming CAD support.
- Admin Studio region-annotation canvas UI and the probation dashboard / API
  routes build on the data model, contracts, and services delivered here.
