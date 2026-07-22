# Stage 2 Web Control and Mac USB Camera Report

> This is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

> Model note: Qwen is the currently configured default LLM/VLM provider for
> this sandbox. Giraffe QC remains provider-neutral; it is not a Qwen ecosystem
> product and no product contract depends on a Qwen-specific model name.

**Status:** superseded — acceptance stopped; Stage 3 entry withdrawn

**Superseded on:** 2026-07-22 (Asia/Hong_Kong)

This report records a historical smoke run only. It does not satisfy the
revised PRD because the standard-sample authoring flow, comprehensive
checkpoint coverage, CV-first routing, conditional 30B escalation and current
capture confirmation flow were not validated together. A fresh Stage 2
acceptance run is required after P0 remediation.

**Acceptance time:** 2026-07-21 (Asia/Hong_Kong)

**Browser scope:** The in-app browser was used only as a temporary Pad/camera
device for Stage 2 qc-model acceptance. It is not part of the production
topology and must be removed from the path when Jetson is online.

## Verified

- The in-app browser opened the real product welcome page and navigated the
  Administrator and Operator branches.
- English/Chinese switching was verified after login on Admin Studio, Operator
  workspace, inspection and report pages.
- Admin Studio made a live text request to the configured AIVAN text assistant:
  qwen3.5:9b, 19.5 seconds.
- The browser enumerated and selected USB 2.0 Camera (1c45:6200) independently
  from the Mac FaceTime camera, displayed a live preview, captured a frame and
  persisted it with source mac_usb_camera.
- The Operator UI created a real tenant-scoped inspection job backed by the
  configured CTYUN MySQL database.
- Before evidence was attached, checkpoint submission was rejected with
  Inspection job has no attached evidence.
- After capture, the Operator UI ran the configured provider-neutral vision
  gateway against the USB frame and the job's exact four checkpoints. The live
  sandbox model was qwen3-vl-4b-mnn; measured model time was 23,431 ms.
- The captured frame did not show the carton/barcode/seal evidence required by
  the selected standard. Missing model checkpoint output was normalized to
  not_visible; operator review and finalization produced review_required,
  never a silent pass.
- The persisted audit chain links one camera media record, one live model result
  and four checkpoint results to job
  75999489cb5d42209449951a09668640.
- The bilingual report page loaded the persisted REVIEW_REQUIRED result and
  all four not_visible checkpoints.
- Full repository regression: 1,171 passed, 6 skipped, 0 failed.

## Stage 3 entry decision (withdrawn)

Stage 3 entry is not allowed from this report. The earlier decision was based
on an obsolete flow and is explicitly withdrawn. Stage 2 must be re-run from
standard-sample acquisition through server-side finalization after the P0
remediation is deployed.

## Stage 3 focus

- Replace the temporary browser device path with the real Pad/Jetson path.
- Compare Jetson-local qwen3-vl-4b with remote-hosted qwen3-vl-4b using the
  same captured frames and snapshotted standard revisions.
- Include positive, negative, obscured and low-confidence physical samples;
  the Stage 2 USB frame only established the fail-closed path, not visual model
  accuracy.
