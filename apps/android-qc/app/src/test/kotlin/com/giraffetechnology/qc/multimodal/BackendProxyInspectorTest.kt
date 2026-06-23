package com.giraffetechnology.qc.multimodal

import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class BackendProxyInspectorTest {

    private val qcPoints = listOf(
        QcPointInput("qp_001", "COLOR", "Color", "Color check"),
        QcPointInput("qp_002", "LABEL", "Label", "Label check"),
    )
    private val ctx = InspectionContext("t1", "sku1", "std1", "insp1")
    private val captured = CapturePhotoInput("c1", "/captured/prod.jpg")

    @Test
    fun `blank base url returns review_required without network call`() = runTest {
        val inspector = BackendProxyInspector(baseUrl = "")
        val result = inspector.inspect(emptyList(), captured, qcPoints, ctx)
        assertEquals("review_required", result.overallResult)
        assertEquals("backend_url_not_configured", result.fallback?.reason)
    }

    @Test
    fun `blank base url fills all items as review_required`() = runTest {
        val inspector = BackendProxyInspector(baseUrl = "")
        val result = inspector.inspect(emptyList(), captured, qcPoints, ctx)
        assertEquals(qcPoints.size, result.items.size)
        for (item in result.items) {
            assertEquals("review_required", item.result)
        }
    }

    @Test
    fun `inspector name is backend_proxy`() {
        assertEquals("backend_proxy", BackendProxyInspector("").inspectorName)
    }

    @Test
    fun `contract version is current contract version`() {
        val inspector = BackendProxyInspector("http://localhost:8080")
        assertEquals(SharedQcContract.QC_CONTRACT_VERSION, inspector.contractVersion)
    }

    @Test
    fun `fallback used is false for blank url error`() = runTest {
        val result = BackendProxyInspector("").inspect(emptyList(), captured, qcPoints, ctx)
        assertEquals(false, result.fallback?.used)
    }

    @Test
    fun `overall result is review_required for blank url`() = runTest {
        val result = BackendProxyInspector("").inspect(emptyList(), captured, qcPoints, ctx)
        assertTrue(SharedQcContract.isValidResult(result.overallResult))
        assertEquals("review_required", result.overallResult)
    }
}
