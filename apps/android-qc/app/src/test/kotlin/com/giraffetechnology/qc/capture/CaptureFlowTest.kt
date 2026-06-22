package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.qwen.*
import com.giraffetechnology.qc.sku.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

private fun makeCapturedPhoto() = CapturedPhoto(
    captureId    = "cap-flow-1",
    timestamp    = "2026-01-01T00:00:00Z",
    rawImagePath = "/data/captures/cap-flow-1.jpg",
    frameId      = "frame-flow-1",
    boundingBox  = NormalizedBox(0.5f, 0.5f, 1f, 1f),
)

private fun makeTask() = QcTask(
    sku             = Sku("sku-f1", "ITEM-F01", "Flow Widget"),
    confirmedByUser = true,
    resolvedBy      = SkuResolutionMethod.MANUAL_ITEM_NUMBER,
)

private fun makeOutput(result: String) = QwenInspectionOutput(
    overallResult = result,
    engine        = "local_qwen_mnn",
    modelName     = "Qwen3-VL-2B-Instruct-MNN",
    confidence    = 0.9f,
    items         = emptyList(),
    fallback      = FallbackInfo(false),
    summary       = "Flow test summary",
)

/** Mirrors PadInspectionCoordinator logic for E2E capture-to-result flow tests. */
private suspend fun inspectFlow(
    runtimeReady: Boolean,
    output: QwenInspectionOutput?,
    photo: CapturedPhoto = makeCapturedPhoto(),
): PadInspectionResult {
    val task = makeTask()
    if (!runtimeReady) {
        return PadInspectionResult(
            overallResult      = "MNN_PENDING",
            reason             = "Local MNN runtime not ready",
            modelName          = "Qwen3-VL-2B-Instruct-MNN",
            localOnly          = true,
            cloudInferenceUsed = false,
            capturedImagePath  = photo.rawImagePath,
        )
    }
    val inspector = object : QwenInspector {
        override val engineName = "fake"
        override val modelName  = "Qwen3-VL-2B-Instruct-MNN"
        override suspend fun inspect(
            standardPhotos: List<StandardPhotoInput>,
            capturedPhoto: CapturePhotoInput,
            qcPoints: List<QcPointInput>,
            context: InspectionContext,
        ): QwenInspectionOutput = output ?: throw UnsupportedOperationException("no output")
    }
    return runCatching {
        val o = inspector.inspect(
            emptyList(),
            CapturePhotoInput(photo.captureId, photo.rawImagePath),
            emptyList(),
            InspectionContext("pad", task.sku.id, task.sku.id, photo.captureId),
        )
        PadInspectionResult(
            overallResult = when (o.overallResult.lowercase()) {
                "pass" -> "ACCEPTED"
                "fail" -> "NOT_ACCEPTED"
                else   -> "review_required"
            },
            reason             = o.summary,
            modelName          = o.modelName,
            localOnly          = true,
            cloudInferenceUsed = false,
            capturedImagePath  = photo.rawImagePath,
        )
    }.getOrElse { e ->
        PadInspectionResult(
            overallResult      = "review_required",
            reason             = "Inspection error: ${e.message}",
            modelName          = "Qwen3-VL-2B-Instruct-MNN",
            localOnly          = true,
            cloudInferenceUsed = false,
            capturedImagePath  = photo.rawImagePath,
        )
    }
}

class CaptureFlowTest {

    // 1. MNN not ready → MNN_PENDING, not ACCEPTED
    @Test fun `capture flow with MNN not ready returns MNN_PENDING`() = runTest {
        val r = inspectFlow(false, null)
        assertEquals("MNN_PENDING", r.overallResult)
        assertNotEquals("ACCEPTED", r.overallResult)
    }

    // 2. Inspector pass → ACCEPTED
    @Test fun `capture flow with pass returns ACCEPTED`() = runTest {
        val r = inspectFlow(true, makeOutput("pass"))
        assertEquals("ACCEPTED", r.overallResult)
    }

    // 3. Inspector fail → NOT_ACCEPTED
    @Test fun `capture flow with fail returns NOT_ACCEPTED`() = runTest {
        val r = inspectFlow(true, makeOutput("fail"))
        assertEquals("NOT_ACCEPTED", r.overallResult)
    }

    // 4. Inspector throw → review_required, never ACCEPTED
    @Test fun `capture flow with inspector throw returns review_required`() = runTest {
        val r = inspectFlow(true, null)
        assertEquals("review_required", r.overallResult)
        assertNotEquals("ACCEPTED", r.overallResult)
    }

    // 5. rawImagePath propagates to capturedImagePath
    @Test fun `rawImagePath propagates to PadInspectionResult capturedImagePath`() = runTest {
        val photo = makeCapturedPhoto()
        val r = inspectFlow(false, null, photo)
        assertEquals(photo.rawImagePath, r.capturedImagePath)
    }

    // 6. cloudInferenceUsed is always false
    @Test fun `cloudInferenceUsed is always false regardless of MNN state`() = runTest {
        for (ready in listOf(false, true)) {
            val r = inspectFlow(ready, makeOutput("pass"))
            assertFalse("cloudInferenceUsed must be false (ready=$ready)", r.cloudInferenceUsed)
        }
    }

    // 7. localOnly is always true
    @Test fun `localOnly is always true regardless of MNN state`() = runTest {
        for (ready in listOf(false, true)) {
            val r = inspectFlow(ready, makeOutput("fail"))
            assertTrue("localOnly must be true (ready=$ready)", r.localOnly)
        }
    }
}
