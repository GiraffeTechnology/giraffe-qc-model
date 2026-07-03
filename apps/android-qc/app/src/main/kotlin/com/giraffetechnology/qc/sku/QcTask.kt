package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput

/**
 * A user-confirmed QC task bound to a SKU.
 *
 * Carries the full Pad-side inspection data contract so PadInspectionCoordinator
 * can run a local inspection without re-fetching: tenant context, the active
 * standard revision id, the standard reference photos, and the detection points.
 *
 * [standardPhotos] / [qcPoints] default to the resolved SKU's lists. If either is
 * empty the Pad must fail closed (review_required / MNN_PENDING), never ACCEPTED.
 */
data class QcTask(
    val sku: Sku,
    val confirmedByUser: Boolean,
    val resolvedBy: SkuResolutionMethod,
    val tenantId: String = "pad",
    val activeStandardRevisionId: String? = sku.activeStandardRevisionId,
    val standardPhotos: List<StandardPhotoInput> = sku.standardPhotos,
    val qcPoints: List<QcPointInput> = sku.detectionPoints,
    /**
     * Bundle version the selected standard was installed from (S6 §9). Carried so
     * a submitted result records exactly which bundle produced the standard the
     * Server can recompute against. Null for the online/backend task path, which
     * has no installed bundle.
     */
    val bundleVersion: String? = null,
)

enum class SkuResolutionMethod { MANUAL_ITEM_NUMBER, MANUAL_REFERENCE_PHOTO, MNN_PHOTO_MATCH }
