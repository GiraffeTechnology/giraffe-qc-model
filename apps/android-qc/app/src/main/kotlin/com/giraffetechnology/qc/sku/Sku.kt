package com.giraffetechnology.qc.sku

data class Sku(
    val id: String,
    val itemNumber: String,
    val name: String,
    val standardPhotoPath: String? = null,
)
