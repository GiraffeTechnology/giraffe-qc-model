package com.giraffetechnology.qc.sku

data class QcTask(
    val taskId: String,
    val sku: Sku,
    val createdAtUtc: String,
    val resolvedBy: SkuResolutionMethod,
    val confirmedByUser: Boolean,
)

enum class SkuResolutionMethod {
    MANUAL_ITEM_NUMBER,
    MANUAL_REFERENCE_PHOTO,
    MNN_PHOTO_MATCH,
}
