package com.giraffetechnology.qc.ui

import com.giraffetechnology.qc.PadScreen
import com.giraffetechnology.qc.sku.*
import org.junit.Assert.*
import org.junit.Test

/**
 * Navigation flow tests covering the new E2E path:
 * MNN-candidate confirmed task -> QcCapture, captured-image result -> Result.
 */
class NavigationFlowTest {

    private val mnnCandidateSku = Sku("sku-mnn", "ITEM-MNN", "MNN Widget")
    private val mnnTask = QcTask(
        sku             = mnnCandidateSku,
        confirmedByUser = true,
        resolvedBy      = SkuResolutionMethod.MNN_PHOTO_MATCH,
    )
    private val capturedResult = PadInspectionResult(
        overallResult      = "MNN_PENDING",
        reason             = "Runtime not ready",
        modelName          = "Qwen3-VL-2B-Instruct-MNN",
        localOnly          = true,
        cloudInferenceUsed = false,
        capturedImagePath  = "/data/captures/cap-nav.jpg",
    )

    // Flow 1: MNN-candidate task navigates to QcCapture preserving MNN_PHOTO_MATCH
    @Test fun `MNN-confirmed task navigates to QcCapture with MNN_PHOTO_MATCH resolution`() {
        var screen: PadScreen = PadScreen.TaskSelection
        val onConfirmed = { task: QcTask -> screen = PadScreen.QcCapture(task) }

        onConfirmed(mnnTask)

        assertTrue("Expected QcCapture but was $screen", screen is PadScreen.QcCapture)
        val captureScreen = screen as PadScreen.QcCapture
        assertEquals(SkuResolutionMethod.MNN_PHOTO_MATCH, captureScreen.task.resolvedBy)
        assertEquals(mnnCandidateSku.id, captureScreen.task.sku.id)
    }

    // Flow 2: inspection result with non-null capturedImagePath navigates to Result
    @Test fun `inspection result with captured path navigates to Result and preserves path`() {
        var screen: PadScreen = PadScreen.QcCapture(mnnTask)
        val onResult = { result: PadInspectionResult -> screen = PadScreen.Result(mnnTask, result) }

        onResult(capturedResult)

        assertTrue("Expected Result but was $screen", screen is PadScreen.Result)
        val resultScreen = screen as PadScreen.Result
        assertEquals(capturedResult.capturedImagePath, resultScreen.result.capturedImagePath)
        assertNotNull(resultScreen.result.capturedImagePath)
        assertNotEquals("ACCEPTED", resultScreen.result.overallResult)
    }
}
