package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.junit.Assert.*
import org.junit.Test

private val testSku  = Sku("sku-confirm-1", "ITEM-CFM", "Confirm Widget")
private val testCand = SkuCandidate(testSku, 0.92f, "/photos/std-cfm.jpg")

private val readyMatcher = object : SkuMatcher {
    override val runtimeState: StateFlow<MnnRuntimeState> = MutableStateFlow(MnnRuntimeState.Ready)
    override suspend fun match(capturedImagePath: String) = SkuMatchResult(
        MatchStatus.OK, listOf(testCand), capturedImagePath
    )
}

class PhotoMatchConfirmationTest {

    // 1. confirmCandidate resolves via MNN_PHOTO_MATCH
    @Test fun `confirmCandidate produces MNN_PHOTO_MATCH resolution`() {
        val ctrl = TaskSelectionController(FakeSkuRepository(listOf(testSku)), readyMatcher)
        ctrl.confirmCandidate(testCand)
        val state = ctrl.state.value
        assertTrue(state is TaskSelectionState.TaskConfirmed)
        assertEquals(
            SkuResolutionMethod.MNN_PHOTO_MATCH,
            (state as TaskSelectionState.TaskConfirmed).task.resolvedBy,
        )
    }

    // 2. confirmCandidate carries the candidate's sku into the confirmed task
    @Test fun `confirmCandidate carries candidate sku into confirmed task`() {
        val ctrl = TaskSelectionController(FakeSkuRepository(listOf(testSku)), readyMatcher)
        ctrl.confirmCandidate(testCand)
        val task = (ctrl.state.value as TaskSelectionState.TaskConfirmed).task
        assertEquals(testSku.id, task.sku.id)
        assertEquals(testSku.itemNumber, task.sku.itemNumber)
        assertTrue(task.confirmedByUser)
    }

    // 3. confirmManual resolves via MANUAL_ITEM_NUMBER, not MNN_PHOTO_MATCH
    @Test fun `confirmManual produces MANUAL_ITEM_NUMBER not MNN_PHOTO_MATCH`() {
        val ctrl = TaskSelectionController(FakeSkuRepository(listOf(testSku)), readyMatcher)
        ctrl.confirmManual(testSku, SkuResolutionMethod.MANUAL_ITEM_NUMBER)
        val task = (ctrl.state.value as TaskSelectionState.TaskConfirmed).task
        assertEquals(SkuResolutionMethod.MANUAL_ITEM_NUMBER, task.resolvedBy)
        assertNotEquals(SkuResolutionMethod.MNN_PHOTO_MATCH, task.resolvedBy)
    }
}
