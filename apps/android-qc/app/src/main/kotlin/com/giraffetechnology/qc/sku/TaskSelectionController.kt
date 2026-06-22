package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class TaskSelectionState {
    object Idle : TaskSelectionState()
    /** Backend search in progress. */
    object SearchingBackend : TaskSelectionState()
    data class BackendError(val message: String) : TaskSelectionState()
    data class ManualResults(val results: List<Sku>) : TaskSelectionState()
    /** MNN runtime is not ready; runMatch() cannot proceed. */
    object MnnPending : TaskSelectionState()
    data class MatchCandidates(val result: SkuMatchResult) : TaskSelectionState()
    data class ReviewRequired(val reason: String) : TaskSelectionState()
    object NoMatch : TaskSelectionState()
    data class TaskConfirmed(val task: QcTask) : TaskSelectionState()
}

/**
 * Manages SKU task selection for a QC session.
 *
 * All confirmation paths require explicit user action — no auto-binding.
 * runMatch() transitions to MnnPending when the local runtime is not ready.
 */
class TaskSelectionController(
    private val skuRepo: SkuRepository,
    private val matcher: SkuMatcher,
) {
    private val _state = MutableStateFlow<TaskSelectionState>(TaskSelectionState.Idle)
    val state: StateFlow<TaskSelectionState> = _state.asStateFlow()

    suspend fun searchByItemNumber(query: String) {
        _state.value = TaskSelectionState.SearchingBackend
        runCatching {
            val results = skuRepo.findByItemNumber(query)
            _state.value = TaskSelectionState.ManualResults(results)
        }.onFailure { e ->
            _state.value = TaskSelectionState.BackendError(e.message ?: "Unknown error")
        }
    }

    suspend fun runMatch(capturedImagePath: String) {
        if (matcher.runtimeState.value !is MnnRuntimeState.Ready) {
            _state.value = TaskSelectionState.MnnPending
            return
        }
        val result = matcher.match(capturedImagePath)
        _state.value = when (result.status) {
            MatchStatus.OK             -> TaskSelectionState.MatchCandidates(result)
            MatchStatus.REVIEW_REQUIRED -> TaskSelectionState.ReviewRequired(
                "Ambiguous match — please select SKU manually"
            )
            MatchStatus.NO_MATCH       -> TaskSelectionState.NoMatch
            MatchStatus.MNN_PENDING    -> TaskSelectionState.MnnPending
        }
    }

    /** Confirm a candidate returned by runMatch. Resolves as MNN_PHOTO_MATCH. */
    fun confirmCandidate(candidate: SkuCandidate) {
        _state.value = TaskSelectionState.TaskConfirmed(
            QcTask(
                sku            = candidate.sku,
                confirmedByUser = true,
                resolvedBy     = SkuResolutionMethod.MNN_PHOTO_MATCH,
            )
        )
    }

    /** Confirm a SKU selected manually. resolvedBy must be MANUAL_*. */
    fun confirmManual(sku: Sku, resolvedBy: SkuResolutionMethod) {
        _state.value = TaskSelectionState.TaskConfirmed(
            QcTask(sku = sku, confirmedByUser = true, resolvedBy = resolvedBy)
        )
    }

    fun startCapturingForMatch() { _state.value = TaskSelectionState.Idle }
    fun reset() { _state.value = TaskSelectionState.Idle }
}
