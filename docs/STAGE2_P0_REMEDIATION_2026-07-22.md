# Stage 2 P0 Remediation Record

> **Superseded (2026-07-22, later same day):** the 30B remote vision
> fallback described below has been decommissioned per a production
> decision (STAGE2_QWEN_VISION_PRODUCTION_ASSESSMENT_20260722) — the blind
> 30B counting evaluation in that assessment got 2 of 3 items wrong with
> high stated confidence. Qwen3-VL-4B is now the sole production vision
> model, scoped to counting confirmation and obvious-defect detection; see
> `src/qc_model/studio/ai_gateway.py`. This record is kept as-is for audit
> history; do not treat its fallback/routing description below as current.

**Environment:** on-site sandbox host (path redacted — see internal deployment log)

**Status:** implementation and automated verification complete; interactive
Stage 2 acceptance remains stopped and must be re-run from the first step.

**Stage 3:** not authorized.

## Product and model position

Giraffe QC is provider- and model-neutral. Qwen is the currently configured
default LLM/VLM family, not a required model, product identity, or ecosystem
dependency.

Current Stage 2 defaults:

- Text: Qwen3.5 9B through the configured text gateway.
- Primary vision: on-site `qwen3-vl-4b-mnn`.
- Conditional vision fallback: remote `qwen3-vl-30b-a3b-mnn`.
- The on-site 4B uses CPU in the Stage 2 simulator. This is not Jetson
  performance evidence. The remote 30B vision backend is CUDA on Tesla V100S.

## Implemented P0 changes

1. Standard photos can be captured manually from the USB camera or selected
   from album/file input. Camera capture requires an explicit capture action,
   then an explicit upload confirmation or retake.
2. Standard-photo authoring now asks the primary VLM for a comprehensive,
   concise 3–8 point candidate and records a coverage self-review across count,
   completeness, centering/symmetry, shape, surface, color/finish, assembly and
   readability.
3. Incomplete primary authoring output can be independently reviewed by the
   configured 30B fallback. The merge cannot discard a primary checkpoint.
4. Confirmed checkpoint candidates preserve expected features and normalized
   CV analyzer configuration.
5. Inspection runs configured CV analyzers first and persists their evidence.
   CV remains informational and cannot issue the final verdict.
6. The local 4B evaluates the full captured frame. Only low-confidence or
   not-visible checkpoints are eligible for 30B escalation.
7. A 30B escalation receives only authorized per-checkpoint ROI/CV crops, never
   the full frame. Each JPEG crop is limited to 200 KiB and 768 pixels on its
   longest side. A checkpoint without a crop fails closed locally and is not
   uploaded.
8. Routing decisions, escalation reasons, CV evidence, crop metadata, model
   identity and timings are persisted with the model result.
9. Process-card ingestion now extracts real embedded content from text/CSV,
   DOCX, XLSX and PDF files. Image cards use the configured VLM OCR route.
   Corrupt, encrypted or image-only documents fail closed without fabricated
   content. Legacy DOC/XLS and CAD remain explicitly unsupported/best-effort.
10. Administrator Studio camera controls and coverage status are bilingual in
    Chinese and English and use the shared runtime language switch.

## Verification evidence

- Full repository suite: **1,184 passed, 6 skipped, 0 failed**.
- Focused routing/UI suite: **60 passed, 0 failed**.
- Deployment source hashes match the tested source for the Pad router and AI
  gateway.
- Web service health: active, `/health` returned `{"status":"ok"}`.
- Model health:
  - On-site 4B: online, alias `qwen3-vl-4b-mnn`, Stage 2 CPU backend.
  - Remote 30B: online, hybrid CPU/CUDA, vision backend CUDA, Tesla V100S.
  - Text gateway: online, Qwen3.5 9B listed.
- Real standard-photo primary smoke: 4B returned live JSON in 44,850 ms with
  route `primary`; its incomplete one-point proposal was marked
  `coverage_review.complete=false`, which is eligible for configured 30B
  coverage escalation.
- Automated privacy tests prove that fallback receives the checkpoint crop,
  not the original full frame, and that no crop means no fallback upload.

## Required fresh Stage 2 acceptance

1. Capture or select the standard sample, preview it, and explicitly upload it.
2. Confirm that the proposed standard covers every visible, relevant feature,
   including the flower-center centering checkpoint, before activation.
3. Capture the test object from the Mac USB camera.
4. Observe CV → local 4B → conditional checkpoint-crop-only 30B routing.
5. Review every checkpoint as the operator; do not accept an automatic final
   verdict from either model.
6. Finalize through the server-side rule engine and verify the persisted report
   from the Administrator view.
7. Repeat the complete flow in Chinese and English and verify language switching
   remains available after login.

Only a successful fresh run against the revised PRD may restore Stage 2 pass
status and authorize Stage 3 Jetson A/B testing.
