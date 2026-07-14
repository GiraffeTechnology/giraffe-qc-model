# Stage 2 Web Control and Mac USB Camera Report

> this is a SANDBOX environment, not a production configuration. No test
> conclusion, performance number, or stability result from it may be presented
> as evidence of production readiness; production admission is re-evaluated
> only after Stage 3+4.

> Model note: this flow makes no LLM/VLM call. Qwen is a replaceable configured
> default, not a required model, product identity, or ecosystem dependency.

**Status:** `software_passed_usb_capture_pending`

## Verified

- Chrome opened the real product welcome page and navigated the working
  Administrator and Operator branches.
- English/Chinese switching was verified on the welcome, login, Operator
  workspace and inspection pages.
- The Mac service reached the configured CTYUN MySQL database through the
  approved bridge and loaded four executable sandbox SKUs.
- Chrome created a real tenant-scoped inspection job from the Operator UI.
- Automated tests verified validated `mac_usb_camera` media persistence, the
  no-evidence rejection, exact/atomic checkpoint submission, deterministic
  finalization and persisted report loading.
- 112 targeted regression tests passed.

## Pending acceptance evidence

- No USB camera was present in the Mac USB inventory during this run.
- Chrome camera permission/device enumeration therefore cannot yet produce an
  actual frame, preview screenshot or camera-backed media record.
- Stage 2 acceptance remains open, and Stage 3 must not start, until a camera is
  connected and the Chrome capture-to-report flow is rerun successfully.
