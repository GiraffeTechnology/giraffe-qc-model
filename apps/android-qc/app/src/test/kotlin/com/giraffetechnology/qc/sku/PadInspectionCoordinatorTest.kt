package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.capture.NormalizedBox
import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

/**
 * Fake runtime so the REAL PadInspectionCoordinator can be exercised without an
 * Android Context (MnnRuntimeLoader requires one). This is what makes the
 * MnnRuntime seam valuable: the coordinator's fail-closed logic is tested
 * directly, not via a re-implemented copy.
 */
private class FakeMnnRuntime(state: MnnRuntimeState) : MnnRuntime {
    override val runtimeState: StateFlow<MnnRuntimeState> = MutableStateFlow(state)
}

/** Records the inputs it was called with so tests can assert real data was passed. */
private class RecordingQwenInspector(
    private val output: QwenInspectionOutput? = null,
) : QwenInspector {
    override val engineName = "fake_local"
    override val modelName  = "Qwen3-VL-2B-Instruct-MNN"
    var lastStandardPhotos: List<StandardPhotoInput>? = null
    var lastQcPoints: List<QcPointInput>? = null
    var lastContext: InspectionContext? = null
    var called = false

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        called = true
        lastStandardPhotos = standardPhotos
        lastQcPoints = qcPoints
        lastContext = context
        return output ?: throw UnsupportedOperationException("not provisioned")
    }
}

private fun makeOutput(result: String) = QwenInspectionOutput(
    overallResult = result,
    engine        = "local_qwen_mnn",
    modelName     = "Qwen3-VL-2B-Instruct-MNN",
    confidence    = 0.9f,
    items         = emptyList(),
    fallback      = FallbackInfo(false),
    summary       = "Test summary",
)

private fun makeStandardPhotos() =
    listOf(StandardPhotoInput(photoId = "std-1", localPath = "/factory/std-1.jpg", angle = "front"))

private fun makeQcPoints() = listOf(
    QcPointInput(
        qcPointId   = "p1",
        qcPointCode = "COLOR",
        name        = "Color",
        description = "Color must match standard",
    ),
)

private fun makeTask(
    standardPhotos: List<StandardPhotoInput> = makeStandardPhotos(),
    qcPoints: List<QcPointInput> = makeQcPoints(),
) = QcTask(
    sku = Sku(
        id          = "sku-1",
        itemNumber  = "ITEM-001",
        name        = "Widget",
        standardPhotos = standardPhotos,
        detectionPoints = qcPoints,
    ),
    confirmedByUser          = true,
    resolvedBy               = SkuResolutionMethod.MANUAL_ITEM_NUMBER,
    tenantId                 = "pad-tenant",
    activeStandardRevisionId = "rev-99",
    standardPhotos           = standardPhotos,
    qcPoints                 = qcPoints,
)

private fun makePhoto() = CapturedPhoto(
    captureId    = "cap-1",
    timestamp    = "2024-01-01T00:00:00Z",
    rawImagePath = "/tmp/cap.jpg",
    frameId      = "f-1",
    boundingBox  = NormalizedBox(0.5f, 0.5f, 0.4f, 0.3f),
)

class PadInspectionCoordinatorTest {

    @Test fun `MNN not ready returns MNN_PENDING`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("pass"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.NotReady))
        val result = coord.inspect(makeTask(), makePhoto())
        assertEquals("MNN_PENDING", result.overallResult)
        assertFalse(result.cloudInferenceUsed)
        assertTrue(result.localOnly)
        assertFalse("inspector must not run when runtime is not ready", inspector.called)
    }

    @Test fun `inspector pass returns ACCEPTED`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("pass"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        val result = coord.inspect(makeTask(), makePhoto())
        assertEquals("ACCEPTED", result.overallResult)
        assertFalse(result.cloudInferenceUsed)
        assertTrue(result.localOnly)
    }

    @Test fun `inspector fail returns NOT_ACCEPTED`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("fail"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        assertEquals("NOT_ACCEPTED", coord.inspect(makeTask(), makePhoto()).overallResult)
    }

    @Test fun `inspector review_required returns review_required`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("review_required"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        assertEquals("review_required", coord.inspect(makeTask(), makePhoto()).overallResult)
    }

    @Test fun `inspector throws returns review_required, not ACCEPTED`() = runTest {
        val inspector = RecordingQwenInspector(null) // throws
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        val result = coord.inspect(makeTask(), makePhoto())
        assertEquals("review_required", result.overallResult)
        assertNotEquals("ACCEPTED", result.overallResult)
    }

    @Test fun `cloudInferenceUsed is always false`() = runTest {
        for (state in listOf(MnnRuntimeState.NotReady, MnnRuntimeState.Ready)) {
            val inspector = RecordingQwenInspector(makeOutput("pass"))
            val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(state))
            val result = coord.inspect(makeTask(), makePhoto())
            assertFalse("cloudInferenceUsed must be false", result.cloudInferenceUsed)
        }
    }

    // ── Fail-closed: empty inputs can never produce ACCEPTED ──────────────────

    @Test fun `empty standard photos never returns ACCEPTED`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("pass"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        val result = coord.inspect(makeTask(standardPhotos = emptyList()), makePhoto())
        assertEquals("review_required", result.overallResult)
        assertNotEquals("ACCEPTED", result.overallResult)
        assertFalse("inspector must not run without a standard", inspector.called)
    }

    @Test fun `empty detection points never returns ACCEPTED`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("pass"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        val result = coord.inspect(makeTask(qcPoints = emptyList()), makePhoto())
        assertEquals("review_required", result.overallResult)
        assertNotEquals("ACCEPTED", result.overallResult)
        assertFalse("inspector must not run without detection points", inspector.called)
    }

    @Test fun `passes non-empty standard photos and detection points from task into inspector`() = runTest {
        val inspector = RecordingQwenInspector(makeOutput("pass"))
        val coord = PadInspectionCoordinator(inspector, FakeMnnRuntime(MnnRuntimeState.Ready))
        val task = makeTask()
        coord.inspect(task, makePhoto())

        assertTrue(inspector.called)
        assertEquals(task.standardPhotos, inspector.lastStandardPhotos)
        assertEquals(task.qcPoints, inspector.lastQcPoints)
        assertTrue(inspector.lastStandardPhotos!!.isNotEmpty())
        assertTrue(inspector.lastQcPoints!!.isNotEmpty())
        // Context carries the task's tenant + snapshotted standard revision.
        assertEquals("pad-tenant", inspector.lastContext!!.tenantId)
        assertEquals("rev-99", inspector.lastContext!!.standardId)
        assertEquals("sku-1", inspector.lastContext!!.skuId)
    }
}
