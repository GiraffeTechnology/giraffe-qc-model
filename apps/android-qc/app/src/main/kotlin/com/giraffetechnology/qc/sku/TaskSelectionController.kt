package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class TaskSelectionState {
    object Idle : TaskSelectionState()
    /** MNN runtime is not ready; runMatch() cannot proceed. */
    object MnnPending : TaskSelectionState()
    data class ManualResults(val results: List<Sku>) : TaskSelectionState()
    data class MatchCandidates(val result: SkuMatchResult) : TaskSelectionState()
    data class TaskConfirmed(val task: QcTask) : TaskSelectionState()
}

/**
 * Manages SKU task selection for a QC session.
 *
 * All task confirmation paths require explicit user action — there is no
 * auto-binding. runMatch() transitions to MnnPending when the local
 * runtime is not ready, never returning a fabricated result.
 */
class TaskSelectionController(
    private val skuRepo: SkuRepository,
    private val matcher: SkuMatcher,
) {
    private val _state = MutableStateFlow<TaskSelectionState>(TaskSelectionState.Idle)
    val state: StateFlow<TaskSelectionState> = _state.asStateFlow()

    suspend fun searchByItemNumber(query: String) {
        val results = skuRepo.findByItemNumber(query)
        _state.value = TaskSelectionState.ManualResults(results)
    }

    suspend fun runMatch(capturedImagePath: String) {
        if (matcher.runtimeState.value !is MnnRuntimeState.Ready) {
            _state.value = TaskSelectionState.MnnPending
            return
        }
        val result = matcher.match(capturedImagePath)
        _state.value = TaskSelectionState.MatchCandidates(result)
    }

    /** Confirm a candidate returned by runMatch. Resolves as MNN_PHOTO_MATCH. */
    fun confirmCandidate(candidate: SkuCandidate) {
        _state.value = TaskSelectionState.TaskConfirmed(
            QcTask(
                sku = candidate.sku,
                confirmedByUser = true,
                resolvedBy = SkuResolutionMethod.MNN_PHOTO_MATCH,
            )
        )
    }

    /** Confirm a SKU selected manually. resolvedBy must be MANUAL_*. */
    fun confirmManual(sku: Sku, resolvedBy: SkuResolutionMethod) {
        _state.value = TaskSelectionState.TaskConfirmed(
            QcTask(sku = sku, confirmedByUser = true, resolvedBy = resolvedBy)
        )
    }

    /** Return to Idle to begin a new capture-for-match cycle. */
    fun startCapturingForMatch() {
        _state.value = TaskSelectionState.Idle
    }

    fun reset() {
        _state.value = TaskSelectionState.Idle
    }
}
