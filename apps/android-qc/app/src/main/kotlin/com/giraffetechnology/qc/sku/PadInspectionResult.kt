package com.giraffetechnology.qc.sku

/**
 * Result of an Operator inspection attempt. Architecture v2 uses the cloud;
 * localOnly remains for explicit legacy compatibility and is false by default.
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
    val cloudJobId: String? = null,
    val pointResultsJson: String? = null,
    val timing: Map<String, String> = emptyMap(),
)
