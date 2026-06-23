package com.giraffetechnology.qc.multimodal

import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class MultimodalInspectionRouterTest {

    private val stdPhotos = listOf(StandardPhotoInput("s1", "/std/front.jpg"))
    private val captured = CapturePhotoInput("c1", "/captured/prod.jpg")
    private val qcPoints = listOf(
        QcPointInput("qp_001", "COLOR", "Color", "Color consistency"),
        QcPointInput("qp_002", "LABEL", "Label", "Label presence"),
    )
    private val ctx = InspectionContext("tenant1", "sku1", "std1", "insp1")

    private fun router(
        config: MultimodalProviderConfig,
        localMnn: MultimodalInspector? = null,
        backendProxy: MultimodalInspector? = null,
        mock: MultimodalInspector? = null,
    ) = MultimodalInspectionRouter(config, localMnn, backendProxy, mock)

    @Test
    fun `mock mode returns mock result`() = runTest {
        val r = router(
            MultimodalProviderConfig.TEST_MOCK,
            mock = MockInspector("pass", 0.95f),
        ).route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
        assertEquals("mock", r.engine)
    }

    @Test
    fun `local MNN pass accepted when confidence meets threshold`() = runTest {
        val r = router(
            MultimodalProviderConfig.DEFAULT,
            localMnn = StubInspector("local_mnn", "pass", 0.93f),
        ).route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
    }

    @Test
    fun `local MNN fail is final - backend proxy not reached`() = runTest {
        // backend proxy returns pass with high confidence, but must never be called
        val r = router(
            MultimodalProviderConfig.withBackendProxy("http://server:8080"),
            localMnn = StubInspector("local_mnn", "fail", 0.91f),
            backendProxy = StubInspector("backend_proxy", "pass", 0.99f),
        ).route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("fail", r.overallResult)
        // Engine must be local_mnn, not backend_proxy
        assertNotEquals("backend_proxy", r.engine)
    }

    @Test
    fun `local MNN below min confidence falls through to backend proxy`() = runTest {
        val r = router(
            MultimodalProviderConfig.withBackendProxy("http://server:8080"),
            localMnn = StubInspector("local_mnn", "pass", 0.50f),  // below 0.82 threshold
            backendProxy = StubInspector("backend_proxy", "pass", 0.95f),
        ).route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
        assertEquals("backend_proxy", r.engine)
    }

    @Test
    fun `no provider configured returns review_required`() = runTest {
        val r = router(
            MultimodalProviderConfig(
                localMnnEnabled = false,
                backendProxyEnabled = false,
                mockEnabled = false,
            ),
        ).route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
        assertEquals("no_provider_available", r.fallback?.reason)
    }

    @Test
    fun `all returned items have canonical result values`() = runTest {
        val r = router(
            MultimodalProviderConfig.TEST_MOCK,
            mock = MockInspector("review_required"),
        ).route(stdPhotos, captured, qcPoints, ctx)
        assertEquals(qcPoints.size, r.items.size)
        for (item in r.items) {
            assertTrue(
                "Item ${item.qcPointId} has non-canonical result: ${item.result}",
                SharedQcContract.isValidResult(item.result),
            )
        }
    }

    @Test
    fun `mock mode uses provided mock inspector over default`() = runTest {
        val customMock = StubInspector("custom_mock", "fail", 0.88f)
        val r = router(MultimodalProviderConfig.TEST_MOCK, mock = customMock)
            .route(stdPhotos, captured, qcPoints, ctx)
        assertEquals("fail", r.overallResult)
        assertEquals("custom_mock", r.engine)
    }

    @Test
    fun `directCloudEnabled=true rejected by config constructor`() {
        try {
            MultimodalProviderConfig(directCloudEnabled = true)
            fail("Expected IllegalArgumentException for directCloudEnabled=true")
        } catch (e: IllegalArgumentException) {
            assertTrue(e.message?.contains("PAD_ALLOW_DIRECT_CLOUD") == true)
        }
    }
}

/** Simple stub inspector returning a fixed result from a named engine. */
private class StubInspector(
    override val inspectorName: String,
    private val result: String,
    private val conf: Float,
) : MultimodalInspector {
    override val modelName: String = "stub_model"

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        val r = SharedQcContract.normalizeResult(result)
        return QwenInspectionOutput(
            overallResult = r,
            engine        = inspectorName,
            modelName     = modelName,
            confidence    = conf,
            items         = qcPoints.map { p ->
                InspectionItemResult(p.qcPointId, p.qcPointCode, p.name, r, conf, "stub")
            },
            fallback = FallbackInfo(used = false),
            summary  = "Stub: $r",
        )
    }
}
