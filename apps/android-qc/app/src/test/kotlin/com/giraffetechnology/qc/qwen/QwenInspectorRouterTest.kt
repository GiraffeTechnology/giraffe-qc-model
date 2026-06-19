package com.giraffetechnology.qc.qwen

import com.giraffetechnology.qc.qwen.fake.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

/**
 * Router tests for the Android Pad local-only branch.
 *
 * Cloud tests that existed on main have been replaced with Pad safety invariant tests:
 *   - All failure paths must produce review_required.
 *   - Cloud is FORBIDDEN: even passing cloudInspector and cloudEnabled=true, the
 *     Pad router must never call cloud and must never produce a cloud-sourced pass.
 *   - local fail → cloud pass escalation is FORBIDDEN.
 */
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

    // --- Fail is final — no cloud escalation ---

    @Test fun `on-device fail is final — cloud inspector is never called`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("fail", 0.95f),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.99f),
            config            = RouterConfig(cloudEnabled = true, onDeviceFailIsFinal = true),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("fail should remain fail — cloud forbidden on Pad branch", "fail", r.overallResult)
    }

    @Test fun `on-device fail with onDeviceFailIsFinal false still returns fail on Pad branch`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("fail", 0.95f),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.99f),
            config            = RouterConfig(cloudEnabled = true, onDeviceFailIsFinal = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        // isAcceptable returns false for "fail" (confidence check irrelevant for fail)
        // Router falls to makeReviewRequired — not cloud
        assertNotEquals("cloud-sourced pass is FORBIDDEN on Pad branch", "pass", r.overallResult)
    }

    // --- Low confidence → review_required (no cloud) ---

    @Test fun `low confidence with cloud disabled returns review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("pass", 0.50f),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
        r.items.forEach { assertEquals("review_required", it.result) }
    }

    @Test fun `low confidence with cloudEnabled flag still returns review_required on Pad`() = runBlocking {
        // cloudEnabled flag is ignored on the Pad branch — cloud is never called
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("pass", 0.50f),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.99f),
            config            = RouterConfig(cloudEnabled = true, minConfidence = 0.82f),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
        assertFalse("Cloud fallback.used must be false — cloud not called on Pad", r.fallback.used)
    }

    // --- On-device error → review_required ---

    @Test fun `on-device runtime error returns review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FailingOnDeviceQwenInspector(),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    @Test fun `on-device error does not escalate to cloud — fallback used must be false`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FailingOnDeviceQwenInspector(),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 0.99f),
            config            = RouterConfig(cloudEnabled = true),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("Cloud must never be called — result must be review_required",
            "review_required", r.overallResult)
        assertFalse("fallback.used must be false — cloud was not used", r.fallback.used)
    }

    // --- Timeout → review_required ---

    @Test fun `on-device timeout returns review_required`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = TimeoutOnDeviceQwenInspector(delayMs = 200L),
            config            = RouterConfig(onDeviceTimeoutMs = 50L, cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- Not provisioned → review_required ---

    @Test fun `not-provisioned inspector returns review_required`() = runBlocking {
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

    // --- review_required is not accepted ---

    @Test fun `review_required on-device result is not accepted`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = InvalidJsonOnDeviceQwenInspector(),
            config            = RouterConfig(cloudEnabled = false),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals("review_required", r.overallResult)
    }

    // --- Item coverage ---

    @Test fun `result items count matches qc_points count`() = runBlocking {
        val router = QwenInspectionRouter(FakeOnDeviceQwenInspector("pass", 0.95f))
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertEquals(qcPoints.size, r.items.size)
    }

    // --- Pad branch safety invariants ---

    @Test fun `local fail never produces pass even if cloud inspector would say pass`() = runBlocking {
        val router = QwenInspectionRouter(
            onDeviceInspector = FakeOnDeviceQwenInspector("fail", 0.95f),
            cloudInspector    = FakeOnDeviceQwenInspector("pass", 1.0f),
            config            = RouterConfig(cloudEnabled = true, onDeviceFailIsFinal = true),
        )
        val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
        assertNotEquals("local fail → cloud pass escalation is FORBIDDEN", "pass", r.overallResult)
    }

    @Test fun `all failure modes produce review_required or fail — never cloud-sourced pass`() = runBlocking {
        val failureScenarios: List<Pair<String, QwenInspector>> = listOf(
            "failing"          to FailingOnDeviceQwenInspector(),
            "not_provisioned"  to NotProvisionedOnDeviceQwenInspector(),
            "invalid_json"     to InvalidJsonOnDeviceQwenInspector(),
            "low_confidence"   to FakeOnDeviceQwenInspector("pass", 0.10f),
        )
        val cloudPass = FakeOnDeviceQwenInspector("pass", 1.0f)
        for ((name, inspector) in failureScenarios) {
            val router = QwenInspectionRouter(
                onDeviceInspector = inspector,
                cloudInspector    = cloudPass,
                config            = RouterConfig(cloudEnabled = true),
            )
            val r = router.route(stdPhotos, capPhoto, qcPoints, ctx)
            assertNotEquals(
                "Scenario '$name' must not produce a cloud-sourced pass",
                "pass", r.overallResult,
            )
        }
    }
}
