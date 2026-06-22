package com.giraffetechnology.qc.sku

data class QcTask(
    val sku: Sku,
    val confirmedByUser: Boolean,
    val resolvedBy: SkuResolutionMethod,
)

enum class SkuResolutionMethod { MANUAL_ITEM_NUMBER, MANUAL_REFERENCE_PHOTO, MNN_PHOTO_MATCH }
