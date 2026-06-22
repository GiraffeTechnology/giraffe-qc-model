package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class AutoCaptureControllerTest {

    private val config = AutoCaptureConfig(
        requiredStableFrames      = 5,
        maxCenterDriftRatio       = 0.05f,
        maxAreaChangeRatio        = 0.10f,
        minConfidence             = 0.6f,
        searchTimeoutMs           = 500L,
        lockingTimeoutMs          = 1_000L,
        captureDebounceMs         = 1_500L,
        qualityFailToleranceFrames = 2,
    )

    private lateinit var detector: MockTargetDetector
    private lateinit var ctrl: AutoCaptureController

    private fun frame(path: String = "/tmp/frame.jpg") = CameraFrame(
        frameId              = "f1",
        timestampMs          = System.currentTimeMillis(),
        imagePathOrBufferRef = path,
        widthPx              = 1920,
        heightPx             = 1080,
    )

    private fun goodDetection(cx: Float = 0.5f, cy: Float = 0.5f, w: Float = 0.3f, h: Float = 0.3f) =
        TargetDetection(
            hasCandidate = true,
            confidence   = 0.9f,
            boundingBox  = NormalizedBox(cx, cy, w, h),
            quality      = FrameQuality.GOOD,
        )

    private fun noCandidate() = TargetDetection(
        hasCandidate = false,
        confidence   = 0f,
        boundingBox  = null,
        quality      = FrameQuality.GOOD,
    )

    @Before
    fun setUp() {
        detector = MockTargetDetector()
        ctrl = AutoCaptureController(
            config         = config,
            detector       = detector,
            captureHandler = { f, b ->
                CapturedPhoto("id", "2026-01-01T00:00:00Z", f.imagePathOrBufferRef!!, f.frameId, b)
            },
        )
    }

    @Test
    fun `starts in Idle state`() {
        assertEquals(AutoCaptureState.Idle, ctrl.state.value)
    }

    @Test
    fun `onCameraStreaming transitions to Searching`() {
        ctrl.onCameraStreaming()
        assertEquals(AutoCaptureState.Searching, ctrl.state.value)
    }

    @Test
    fun `processFrame with no candidate stays Searching`() {
        ctrl.onCameraStreaming()
        detector.setNext(noCandidate())
        ctrl.processFrame(frame(), nowMs = 100L)
        assertEquals(AutoCaptureState.Searching, ctrl.state.value)
    }

    @Test
    fun `stable candidate frames lead to Locking then Locked`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection())
        // Frame 1: Searching → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)
        assertEquals(AutoCaptureState.CandidateDetected, ctrl.state.value)
        // Frame 2: CandidateDetected → Locking (stableCount = 1)
        ctrl.processFrame(frame(), nowMs = 200L)
        assertEquals(AutoCaptureState.Locking, ctrl.state.value)
        // Frames 3–6: stableCount 2–5 → Locked when count reaches requiredStableFrames (5)
        repeat(4) { i -> ctrl.processFrame(frame(), nowMs = 300L + i * 100L) }
        assertTrue("expected Locked but was ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Locked)
    }

    @Test
    fun `locking timeout transitions to Rejected LOCKING_TIMEOUT`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection())
        ctrl.processFrame(frame(), nowMs = 0L)    // → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)  // → Locking (lockingStartMs = 100)
        // Advance past lockingTimeoutMs (1 000 ms)
        ctrl.processFrame(frame(), nowMs = 1_200L)
        assertEquals(
            AutoCaptureState.Rejected(RejectReason.LOCKING_TIMEOUT),
            ctrl.state.value,
        )
    }

    @Test
    fun `excessive drift in Locking resets to Searching`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection(cx = 0.5f))
        ctrl.processFrame(frame(), nowMs = 0L)    // → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)  // → Locking
        // Large horizontal drift: 0.2 > maxCenterDriftRatio (0.05)
        detector.setNext(goodDetection(cx = 0.7f))
        ctrl.processFrame(frame(), nowMs = 200L)
        assertEquals(AutoCaptureState.Searching, ctrl.state.value)
    }

    @Test
    fun `bad quality within tolerance skips frame without resetting`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection())
        ctrl.processFrame(frame(), nowMs = 0L)    // → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)  // → Locking (stableCount = 1)

        // qualityFailToleranceFrames = 2; two bad frames stay within tolerance
        val blurry = TargetDetection(
            hasCandidate = true, confidence = 0.9f,
            boundingBox  = NormalizedBox(0.5f, 0.5f, 0.3f, 0.3f),
            quality      = FrameQuality.BLURRY,
        )
        detector.setNext(blurry)
        ctrl.processFrame(frame(), nowMs = 200L)  // qualityFailCount = 1
        ctrl.processFrame(frame(), nowMs = 300L)  // qualityFailCount = 2
        assertTrue("expected Locking but was ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Locking)
    }

    @Test
    fun `bad quality exceeds tolerance resets to Searching`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection())
        ctrl.processFrame(frame(), nowMs = 0L)    // → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)  // → Locking

        val blurry = TargetDetection(
            hasCandidate = true, confidence = 0.9f,
            boundingBox  = NormalizedBox(0.5f, 0.5f, 0.3f, 0.3f),
            quality      = FrameQuality.BLURRY,
        )
        detector.setNext(blurry)
        ctrl.processFrame(frame(), nowMs = 200L)  // qualityFailCount = 1
        ctrl.processFrame(frame(), nowMs = 300L)  // qualityFailCount = 2 (at tolerance)
        ctrl.processFrame(frame(), nowMs = 400L)  // qualityFailCount = 3 > 2 → Searching
        assertEquals(AutoCaptureState.Searching, ctrl.state.value)
    }

    @Test
    fun `locking frame with no candidate resets to Searching`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection())
        ctrl.processFrame(frame(), nowMs = 0L)    // → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)  // → Locking (stableCount = 1)

        // Item leaves the frame: no candidate in the next detection
        detector.setNext(noCandidate())
        ctrl.processFrame(frame(), nowMs = 200L)
        assertEquals(
            "no-candidate frame during Locking must reset to Searching",
            AutoCaptureState.Searching, ctrl.state.value,
        )
    }

    @Test
    fun `locking frame with null boundingBox resets to Searching`() {
        ctrl.onCameraStreaming()
        detector.setNext(goodDetection())
        ctrl.processFrame(frame(), nowMs = 0L)    // → CandidateDetected
        ctrl.processFrame(frame(), nowMs = 100L)  // → Locking (stableCount = 1)

        // Detector signals hasCandidate=true but lost the bounding box
        detector.setNext(TargetDetection(
            hasCandidate = true,
            confidence   = 0.9f,
            boundingBox  = null,
            quality      = FrameQuality.GOOD,
        ))
        ctrl.processFrame(frame(), nowMs = 200L)
        assertEquals(
            "null-boundingBox frame during Locking must reset to Searching",
            AutoCaptureState.Searching, ctrl.state.value,
        )
    }

    @Test
    fun `triggerCapture produces Captured state`() = runTest {
        val box = NormalizedBox(0.5f, 0.5f, 0.3f, 0.3f)
        val f   = frame()
        ctrl.triggerCapture(f, box)
        val s = ctrl.state.value
        assertTrue("expected Captured but was $s", s is AutoCaptureState.Captured)
        val photo = (s as AutoCaptureState.Captured).capture
        assertEquals("id", photo.captureId)
        assertEquals(f.imagePathOrBufferRef, photo.rawImagePath)
        assertEquals(f.frameId, photo.frameId)
        assertEquals(box, photo.boundingBox)
    }

    @Test
    fun `isInDebounce returns true immediately after capture`() = runTest {
        val box = NormalizedBox(0.5f, 0.5f, 0.3f, 0.3f)
        ctrl.triggerCapture(frame(), box)
        assertTrue("expected isInDebounce=true immediately after capture",
            ctrl.isInDebounce())
    }
}
