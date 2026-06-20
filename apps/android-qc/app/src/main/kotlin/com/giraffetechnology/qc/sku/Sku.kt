package com.giraffetechnology.qc.sku

data class Sku(
    val skuId: String,
    val itemNumber: String,
    val name: String,
    val referencePhotoPaths: List<String>,
    val attributes: Map<String, String> = emptyMap(),
)
