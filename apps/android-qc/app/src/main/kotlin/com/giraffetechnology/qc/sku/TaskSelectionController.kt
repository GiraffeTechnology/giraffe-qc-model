package com.giraffetechnology.qc.sku

import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant
import java.util.UUID

/**
 * Drives the TaskSelection state machine (Part 2).
 *
 * Critical gate: MatchCandidates → TaskConfirmed happens ONLY via [confirmCandidate].
 * No automatic advancement is permitted under any similarity value.
 * Operator MUST tap confirm explicitly.
 */
class TaskSelectionController(
    private val repository: SkuRepository,
    private val matcher: SkuMatcher,
) {
    companion object { private const val TAG = "TaskSelectionController" }

    private val _state = MutableStateFlow<TaskSelectionState>(TaskSelectionState.Idle)
    val state: StateFlow<TaskSelectionState> = _state.asStateFlow()

    suspend fun searchByItemNumber(query: String) {
        _state.value = TaskSelectionState.ManualSearching
        runCatching { repository.searchByItemNumber(query) }
            .onSuccess { skus -> _state.value = TaskSelectionState.ManualResults(skus) }
            .onFailure { e  ->
                Log.e(TAG, "searchByItemNumber failed: ${e.message}")
                _state.value = TaskSelectionState.Error(e.message ?: "search failed")
            }
    }

    /** Operator chose a SKU manually (item number or reference photo). Always confirmed. */
    fun confirmManual(sku: Sku, method: SkuResolutionMethod = SkuResolutionMethod.MANUAL_ITEM_NUMBER) {
        require(method != SkuResolutionMethod.MNN_PHOTO_MATCH) {
            "Use confirmCandidate() for MNN_PHOTO_MATCH"
        }
        val task = QcTask(
            taskId         = UUID.randomUUID().toString(),
            sku            = sku,
            createdAtUtc   = Instant.now().toString(),
            resolvedBy     = method,
            confirmedByUser = true,
        )
        Log.i(TAG, "Manual task confirmed: skuId=${sku.skuId} method=$method")
        _state.value = TaskSelectionState.TaskConfirmed(task)
    }

    fun startCapturingForMatch() {
        _state.value = TaskSelectionState.CapturingForMatch
    }

    suspend fun runMatch(capturedImagePath: String) {
        _state.value = TaskSelectionState.Matching
        val result = matcher.match(capturedImagePath)
        _state.value = when (result.status) {
            MatchStatus.MNN_PENDING -> {
                Log.w(TAG, "MNN not ready — MnnPending; manual path available")
                TaskSelectionState.MnnPending
            }
            MatchStatus.NO_MATCH, MatchStatus.REVIEW_REQUIRED, MatchStatus.OK -> {
                TaskSelectionState.MatchCandidates(result)
            }
        }
    }

    /**
     * Operator explicitly confirms a candidate from the match list.
     * This is the ONLY path that creates a TaskConfirmed with MNN_PHOTO_MATCH.
     * Requires state == MatchCandidates.
     */
    fun confirmCandidate(candidate: SkuCandidate) {
        val current = _state.value
        require(current is TaskSelectionState.MatchCandidates) {
            "confirmCandidate called in wrong state: $current"
        }
        val task = QcTask(
            taskId          = UUID.randomUUID().toString(),
            sku             = candidate.sku,
            createdAtUtc    = Instant.now().toString(),
            resolvedBy      = SkuResolutionMethod.MNN_PHOTO_MATCH,
            confirmedByUser = true,
        )
        Log.i(TAG, "MNN candidate confirmed by operator: skuId=${candidate.sku.skuId} sim=${candidate.similarity}")
        _state.value = TaskSelectionState.TaskConfirmed(task)
    }

    fun reset() {
        _state.value = TaskSelectionState.Idle
    }
}
