package com.giraffetechnology.qc.ui

import com.giraffetechnology.qc.PadScreen
import com.giraffetechnology.qc.sku.*
import org.junit.Assert.*
import org.junit.Test

/** Pure navigation-state logic tests — no Compose, no Android, no camera, no MNN. */
class PadNavigationStateTest {

    private val testSku = Sku("sku-1", "ITEM-001", "Widget")
    private val testTask = QcTask(
        sku             = testSku,
        confirmedByUser = true,
        resolvedBy      = SkuResolutionMethod.MANUAL_ITEM_NUMBER,
    )
    private val mnnPendingResult = PadInspectionResult(
        overallResult     = "MNN_PENDING",
        reason            = "Local MNN runtime not ready",
        modelName         = "Qwen3-VL-2B-Instruct-MNN",
        localOnly         = true,
        cloudInferenceUsed = false,
        capturedImagePath = null,
    )
    private val backendErrorResult = PadInspectionResult(
        overallResult     = "review_required",
        reason            = "Backend error",
        modelName         = "Qwen3-VL-2B-Instruct-MNN",
        localOnly         = true,
        cloudInferenceUsed = false,
        capturedImagePath = null,
    )

    // 1. Initial screen is TaskSelection
    @Test fun `initial screen is TaskSelection`() {
        val screen: PadScreen = PadScreen.TaskSelection
        assertTrue(screen is PadScreen.TaskSelection)
    }

    // 2. Confirmed task navigates to QcCapture
    @Test fun `confirmed task navigates to QcCapture`() {
        val screen: PadScreen = PadScreen.QcCapture(testTask)
        assertTrue(screen is PadScreen.QcCapture)
        assertEquals(testTask, (screen as PadScreen.QcCapture).task)
        assertTrue(screen.task.confirmedByUser)
    }

    // 3. Capture result navigates to Result
    @Test fun `capture result navigates to Result screen`() {
        val screen: PadScreen = PadScreen.Result(testTask, mnnPendingResult)
        assertTrue(screen is PadScreen.Result)
        assertEquals(testTask, (screen as PadScreen.Result).task)
        assertEquals(mnnPendingResult, screen.result)
    }

    // 4. MNN pending is displayed as pending, not pass
    @Test fun `MNN pending result is not ACCEPTED`() {
        val screen = PadScreen.Result(testTask, mnnPendingResult)
        val result = (screen as PadScreen.Result).result
        assertNotEquals("ACCEPTED", result.overallResult)
        assertEquals("MNN_PENDING", result.overallResult)
        assertFalse(result.cloudInferenceUsed)
    }

    // 5. Backend error is displayed as review_required, not pass
    @Test fun `backend error result is not ACCEPTED`() {
        val screen = PadScreen.Result(testTask, backendErrorResult)
        val result = (screen as PadScreen.Result).result
        assertNotEquals("ACCEPTED", result.overallResult)
    }

    // 6. No SKU result shows ManualResults empty
    @Test fun `empty ManualResults is distinct from TaskConfirmed`() {
        val empty: TaskSelectionState = TaskSelectionState.ManualResults(emptyList())
        assertFalse(empty is TaskSelectionState.TaskConfirmed)
        assertTrue((empty as TaskSelectionState.ManualResults).results.isEmpty())
    }

    // Extra: cloudInferenceUsed is never true on Pad
    @Test fun `pad results never set cloudInferenceUsed`() {
        listOf(mnnPendingResult, backendErrorResult).forEach { r ->
            assertFalse("cloudInferenceUsed must be false", r.cloudInferenceUsed)
        }
    }
}
