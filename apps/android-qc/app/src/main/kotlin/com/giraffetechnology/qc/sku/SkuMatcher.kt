package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.StateFlow

// ── MNN runtime state (shared with QC inferencer state conceptually, kept separate here) ──

sealed class MnnRuntimeState {
    data object NotReady : MnnRuntimeState()
    data object Loading  : MnnRuntimeState()
    data object Ready    : MnnRuntimeState()
    data class  Error(val reason: String) : MnnRuntimeState()
}

// ── Match result types ──

enum class MatchStatus {
    OK,               // candidates returned; awaiting human confirmation
    MNN_PENDING,      // runtime not ready → fall back to manual
    NO_MATCH,         // ran but nothing passed threshold
    REVIEW_REQUIRED,  // low confidence / Top1 ≈ Top2
}

data class SkuCandidate(
    val sku: Sku,
    val similarity: Float,
    val referencePhotoPathUsed: String?,
)

data class SkuMatchResult(
    val status: MatchStatus,
    val candidates: List<SkuCandidate>,
    val capturedImagePath: String,
)

// ── Interface ──

/**
 * Matches a captured image against in-library reference photos using MNN.
 * NEVER emits QC pass/fail. Even at similarity=0.99 it only produces candidates;
 * the operator MUST confirm before a QcTask is created.
 */
interface SkuMatcher {
    val runtimeState: StateFlow<MnnRuntimeState>
    suspend fun match(capturedImagePath: String): SkuMatchResult
}
