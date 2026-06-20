package com.giraffetechnology.qc.capture

/**
 * Output of a successful auto-capture.
 * After creation: status = MNN pending / review_required.
 * No QC pass/fail until real MNN processes rawImagePath.
 */
data class CapturedPhoto(
    val captureId: String,
    val capturedAtUtc: String,
    val rawImagePath: String,
    val sourceFrameId: String,
    val previewBox: NormalizedBox?,
)
