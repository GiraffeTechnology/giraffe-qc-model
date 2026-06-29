package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

private val testSku  = Sku("sku-confirm-1", "ITEM-CFM", "Confirm Widget")
private val detailedTestSku = testSku.copy(
    activeStandardRevisionId = "rev-confirm-1",
    standardPhotos = listOf(StandardPhotoInput("std-confirm-1", "/photos/std-cfm.jpg")),
    detectionPoints = listOf(
        QcPointInput(
            qcPointId = "point-confirm-1",
            qcPointCode = "center_alignment",
            name = "Center alignment",
            description = "Center must be aligned",
        )
    ),
)
private val testCand = SkuCandidate(detailedTestSku, 0.92f, "/photos/std-cfm.jpg")

private val readyMatcher = object : SkuMatcher {
    override val runtimeState: StateFlow<MnnRuntimeState> = MutableStateFlow(MnnRuntimeState.Ready)
    override suspend fun match(capturedImagePath: String) = SkuMatchResult(
        MatchStatus.OK, listOf(testCand), capturedImagePath
    )
}

class PhotoMatchConfirmationTest {

    @Test fun `confirmCandidate produces MNN_PHOTO_MATCH resolution`() {
        val ctrl = TaskSelectionController(FakeSkuRepository(listOf(detailedTestSku)), readyMatcher)
        ctrl.confirmCandidate(testCand)
        val state = ctrl.state.value
        assertTrue(state is TaskSelectionState.TaskConfirmed)
        assertEquals(
            SkuResolutionMethod.MNN_PHOTO_MATCH,
            (state as TaskSelectionState.TaskConfirmed).task.resolvedBy,
        )
    }

    @Test fun `confirmCandidate carries candidate sku into confirmed task`() {
        val ctrl = TaskSelectionController(FakeSkuRepository(listOf(detailedTestSku)), readyMatcher)
        ctrl.confirmCandidate(testCand)
        val task = (ctrl.state.value as TaskSelectionState.TaskConfirmed).task
        assertEquals(detailedTestSku.id, task.sku.id)
        assertEquals(detailedTestSku.itemNumber, task.sku.itemNumber)
        assertTrue(task.confirmedByUser)
    }

    @Test fun `confirmManual produces MANUAL_ITEM_NUMBER not MNN_PHOTO_MATCH`() = runTest {
        val ctrl = TaskSelectionController(FakeSkuRepository(listOf(detailedTestSku)), readyMatcher)
        ctrl.confirmManual(detailedTestSku, SkuResolutionMethod.MANUAL_ITEM_NUMBER)
        val task = (ctrl.state.value as TaskSelectionState.TaskConfirmed).task
        assertEquals(SkuResolutionMethod.MANUAL_ITEM_NUMBER, task.resolvedBy)
        assertNotEquals(SkuResolutionMethod.MNN_PHOTO_MATCH, task.resolvedBy)
    }
}
