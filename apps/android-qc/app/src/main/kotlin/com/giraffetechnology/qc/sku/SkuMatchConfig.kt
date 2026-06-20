package com.giraffetechnology.qc.sku

data class SkuMatchConfig(
    val confirmThreshold: Float = 0.75f,
    val ambiguityGap: Float = 0.05f,
    val maxCandidates: Int = 3,
)
