package com.giraffetechnology.qc.multimodal

import com.giraffetechnology.qc.qwen.*
import com.giraffetechnology.qc.qwen.fake.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

/**
 * Tests for LocalMnnInspector contract compliance.
 *
 * LocalMnnInspector wraps MnnQwenInspector. Here we test the interface contract
 * using FakeOnDeviceQwenInspector and NotProvisionedOnDeviceQwenInspector
 * as stand-ins for the real MNN inspector, because MnnQwenInspector requires
 * a real Android Context and JNI libraries.
 *
 * The test verifies:
 * - Pass-through delegation: result from underlying inspector is returned unchanged
 * - Contract version is correct
 * - All results are canonical
 * - MockInspector also satisfies the contract (sanity check)
 */
class LocalMnnInspectorTest {

    private val qcPoints = listOf(
        QcPointInput("qp_001", "COLOR", "Color", "Color check"),
        QcPointInput("qp_002", "LABEL", "Label", "Label check"),
    )
    private val stdPhotos = listOf(StandardPhotoInput("s1", "/std/front.jpg"))
    private val captured = CapturePhotoInput("c1", "/captured/prod.jpg")
    private val ctx = InspectionContext("t1", "sku1", "std1", "insp1")

    @Test
    fun `pass through pass result from underlying inspector`() = runTest {
        val underlying = FakeOnDeviceQwenInspector("pass", 0.95f)
        val inspector = DelegatingMultimodalInspector(underlying)
        val result = inspector.inspect(stdPhotos, captured, qcPoints, ctx)
        assertEquals("pass", result.overallResult)
        assertEquals("local_qwen_mnn", result.engine)
    }

    @Test
    fun `pass through fail result from underlying inspector`() = runTest {
        val underlying = FakeOnDeviceQwenInspector("fail", 0.88f)
        val inspector = DelegatingMultimodalInspector(underlying)
        val result = inspector.inspect(stdPhotos, captured, qcPoints, ctx)
        assertEquals("fail", result.overallResult)
    }

    @Test
    fun `not provisioned maps to review_required via router`() = runTest {
        // NotProvisionedOnDeviceQwenInspector throws UnsupportedOperationException.
        // The router catches it and returns review_required.
        val provisioned = NotProvisionedOnDeviceQwenInspector()
        val inspector = ThrowingMultimodalInspector(provisioned)
        val router = MultimodalInspectionRouter(
            config = MultimodalProviderConfig.DEFAULT,
            localMnn = inspector,
        )
        val result = router.route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("review_required", result.overallResult)
    }

    @Test
    fun `contract version is current`() {
        val inspector = MockInspector()
        assertEquals(SharedQcContract.QC_CONTRACT_VERSION, inspector.contractVersion)
    }

    @Test
    fun `all result values are canonical`() = runTest {
        for (resultValue in listOf("pass", "fail", "review_required")) {
            val inspector = MockInspector(resultValue)
            val result = inspector.inspect(stdPhotos, captured, qcPoints, ctx)
            assertTrue(SharedQcContract.isValidResult(result.overallResult))
            for (item in result.items) {
                assertTrue(
                    "Item ${item.qcPointId} non-canonical: ${item.result}",
                    SharedQcContract.isValidResult(item.result),
                )
            }
        }
    }

    @Test
    fun `mock inspector normalizes unknown result to review_required`() = runTest {
        val inspector = MockInspector("ng")  // forbidden value
        val result = inspector.inspect(stdPhotos, captured, qcPoints, ctx)
        assertEquals("review_required", result.overallResult)
    }
}

/**
 * Thin MultimodalInspector adapter that delegates to a QwenInspector.
 * Used here in place of LocalMnnInspector (which requires a real MnnQwenInspector).
 */
private class DelegatingMultimodalInspector(
    private val delegate: QwenInspector,
) : MultimodalInspector {
    override val inspectorName = "local_mnn"
    override val modelName: String get() = delegate.modelName
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ) = delegate.inspect(standardPhotos, capturedPhoto, qcPoints, context)
}

/**
 * MultimodalInspector that calls a QwenInspector and lets exceptions propagate,
 * so the router's exception-catching logic can be tested.
 */
private class ThrowingMultimodalInspector(
    private val delegate: QwenInspector,
) : MultimodalInspector {
    override val inspectorName = "local_mnn"
    override val modelName: String get() = delegate.modelName
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ) = delegate.inspect(standardPhotos, capturedPhoto, qcPoints, context)
}
