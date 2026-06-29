package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput

/**
 * A SKU resolved from the factory backend.
 *
 * [standardPhotos] and [detectionPoints] are the inspection data contract the
 * Pad needs to run a local inspection. They are populated from the SKU detail
 * response (GET /api/v1/sku/{id}); the lightweight search response leaves them
 * empty. A Pad inspection MUST fail closed when either is empty — see
 * PadInspectionCoordinator.
 */
data class Sku(
    val id: String,
    val itemNumber: String,
    val name: String,
    val standardPhotoPath: String? = null,
    val referenceImageUrl: String? = null,
    val activeStandardRevisionId: String? = null,
    val standardPhotos: List<StandardPhotoInput> = emptyList(),
    val detectionPoints: List<QcPointInput> = emptyList(),
)
