package com.giraffetechnology.qc.sku

/**
 * Result of a local pad-side QC inspection attempt.
 *
 * overallResult values: "review_required", "ACCEPTED", "NOT_ACCEPTED", "MNN_PENDING"
 * cloudInferenceUsed is always false on Pad — enforced by PadInspectionCoordinator.
 */
data class PadInspectionResult(
    val overallResult: String,
    val reason: String,
    val modelName: String,
    val localOnly: Boolean,
    val cloudInferenceUsed: Boolean,
    val capturedImagePath: String?,
)
