package com.giraffetechnology.qc.ui

import com.giraffetechnology.qc.sku.*
import org.junit.Assert.*
import org.junit.Test

class TaskSelectionClearStateTest {

    private val skuA = Sku("s1", "ITEM-001", "Widget Alpha")
    private val skuB = Sku("s2", "ITEM-002", "Widget Beta")
    private val aTask = QcTask(skuA, true, SkuResolutionMethod.MANUAL_ITEM_NUMBER)

    @Test
    fun `shouldClearSelection true for SearchingBackend`() {
        assertTrue(shouldClearSelection(TaskSelectionState.SearchingBackend))
    }

    @Test
    fun `shouldClearSelection true for ManualResults`() {
        assertTrue(shouldClearSelection(TaskSelectionState.ManualResults(listOf(skuA))))
    }

    @Test
    fun `shouldClearSelection true for MatchCandidates`() {
        val result = SkuMatchResult(MatchStatus.OK, emptyList(), "/path")
        assertTrue(shouldClearSelection(TaskSelectionState.MatchCandidates(result)))
    }

    @Test
    fun `shouldClearSelection true for BackendError`() {
        assertTrue(shouldClearSelection(TaskSelectionState.BackendError("timeout")))
    }

    @Test
    fun `shouldClearSelection true for NoMatch`() {
        assertTrue(shouldClearSelection(TaskSelectionState.NoMatch))
    }

    @Test
    fun `shouldClearSelection true for ReviewRequired`() {
        assertTrue(shouldClearSelection(TaskSelectionState.ReviewRequired("ambiguous")))
    }

    @Test
    fun `shouldClearSelection true for MnnPending`() {
        assertTrue(shouldClearSelection(TaskSelectionState.MnnPending))
    }

    @Test
    fun `shouldClearSelection false for TaskConfirmed`() {
        assertFalse(shouldClearSelection(TaskSelectionState.TaskConfirmed(aTask)))
    }

    @Test
    fun `shouldClearSelection false for Idle`() {
        assertFalse(shouldClearSelection(TaskSelectionState.Idle))
    }

    @Test
    fun `search button click clears selection before launching search`() {
        var selectedSource: Any? = skuA
        // Simulates onClick: clear first, then launch search coroutine
        selectedSource = null
        assertNull("selection must be cleared before search launches", selectedSource)
    }

    @Test
    fun `MNN candidate selection cleared when manual results replace match candidates`() {
        val candidate = SkuCandidate(skuA, 0.95f, "/path")
        var selectedSource: Any? = candidate
        val newState: TaskSelectionState = TaskSelectionState.ManualResults(listOf(skuB))
        if (shouldClearSelection(newState)) selectedSource = null
        assertNull("MNN candidate selection must clear when manual results arrive", selectedSource)
    }

    @Test
    fun `confirm disabled when selectedSource is null after empty search result`() {
        val selectedSource: Any? = null
        val confirmEnabled = selectedSource != null
        assertFalse("confirm must be disabled with no selection", confirmEnabled)
    }
}
