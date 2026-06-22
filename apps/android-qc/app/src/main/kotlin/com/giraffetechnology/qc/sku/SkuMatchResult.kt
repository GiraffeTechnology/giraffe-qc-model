package com.giraffetechnology.qc.sku

data class SkuMatchResult(
    val status: MatchStatus,
    val candidates: List<SkuCandidate>,
    val capturedImagePath: String,
)

data class SkuCandidate(
    val sku: Sku,
    val similarity: Float,
    val photoPath: String,
)

enum class MatchStatus { OK, REVIEW_REQUIRED, NO_MATCH, MNN_PENDING }
