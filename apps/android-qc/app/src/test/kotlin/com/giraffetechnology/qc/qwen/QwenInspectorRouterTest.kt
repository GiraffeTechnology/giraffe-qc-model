package com.giraffetechnology.qc.qwen

import com.giraffetechnology.qc.qwen.fake.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class QwenInspectorRouterTest {

    private val qcPoints = listOf(
        QcPointInput("QC-01", "color_check",  "Color",  "Surface color match"),
        QcPointInput("QC-02", "border_check", "Border", "Border integrity"),
    )
    private val stdPhotos  = listOf(StandardPhotoInput("STD-1", "/fake/std.jpg", "front"))
    private val capPhoto   = CapturePhotoInput("CAP-1", "/fake/cap.jpg")
    private val ctx        = InspectionContext("t1", "SKU-1", "STD-1", "INS-1")

    // --- On-device pass path ---

    @Test fun `on-device pass above threshold is accepted`() = runBlocking {
        val router = QwenInspectionRouter(FakeOnDeviceQwenInspector("pass", 0.95f))
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
        assertFalse("fallback must not be used", r.fallback.used)
        assertEquals("local_qwen_mnn", r.engine)
    }

    // --- §4.5.4: on-device FAIL is final ---

    @Test fun `on-device fail is final — cloud not called`() = runBlocking {
        val cloud = FakeOnDeviceQwenInspector("pass", 0.99f) // would produce pass if called
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("fail", 0.95f),
            cloudInspector    = cloud,
            config            = RouterConfig(cloudEnabled = true, onDeviceFailIsFinal = true),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("fail should remain fail", "fail", r.overallResult)
    }

    @Test fun `on-device fail with flag disabled falls back to cloud`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("fail", 0.95f),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.99f),
            config            = RouterConfig(cloudEnabled = true, onDeviceFailIsFinal = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
        assertTrue("fallback must be used", r.fallback.used)
    }

    // --- Low confidence → fallback ---

    @Test fun `low confidence triggers cloud fallback`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("pass", 0.50f),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.97f),
            config            = RouterConfig(cloudEnabled = true, minConfidence = 0.82f),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
        assertTrue("fallback used for low confidence", r.fallback.used)
    }

    @Test fun `low confidence with cloud disabled becomes review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("pass", 0.50f),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
        r.items.forEach { assertEquals("review_required", it.result) }
    }

    // --- On-device error paths ---

    @Test fun `on-device runtime error triggers review_required when cloud disabled`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FailingOnDeviceQwenInspector(),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    @Test fun `on-device error triggers cloud fallback when enabled`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FailingOnDeviceQwenInspector(),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.97f),
            config            = RouterConfig(cloudEnabled = true),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("pass", r.overallResult)
        assertTrue(r.fallback.used)
    }

    // --- Timeout path ---

    @Test fun `on-device timeout triggers review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = TimeoutOnDeviceQwenInspector(delayMs = 200L),
            config            = RouterConfig(onDeviceTimeoutMs = 50L, cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- Not provisioned path ---

    @Test fun `not-provisioned inspector triggers review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = NotProvisionedOnDeviceQwenInspector(),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- onDeviceEnabled = false ---

    @Test fun `on-device disabled short-circuits to review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("pass", 0.99f),
            config            = RouterConfig(onDeviceEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- Cloud also fails ---

    @Test fun `cloud fallback failure returns review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FailingOnDeviceQwenInspector(),
            cloudInspector    = FailingOnDeviceQwenInspector(),
            config            = RouterConfig(cloudEnabled = true),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- review_required from on-device treated as non-pass ---

    @Test fun `review_required on-device result is not accepted`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = InvalidJsonOnDeviceQwenInspector(),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- All items covered ---

    @Test fun `result items count matches qc_points count`() = runBlocking {
        val router = QwenInspectionRouter(FakeOnDeviceQwenInspector("pass", 0.95f))
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals(qcPoints.size, r.items.size)
    }
}
