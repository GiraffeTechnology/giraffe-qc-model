package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.UUID

@OptIn(ExperimentalCoroutinesApi::class)
class AutoCaptureControllerTest {

    private val config = AutoCaptureConfig(
        requiredStableFrames       = 5,
        maxCenterDriftRatio        = 0.05f,
        maxAreaChangeRatio         = 0.10f,
        minConfidence              = 0.6f,
        searchTimeoutMs            = 500L,
        lockingTimeoutMs           = 1_000L,
        captureDebounceMs          = 1_500L,
        qualityFailToleranceFrames = 2,
    )

    private val box = NormalizedBox.DEFAULT

    private fun frame(path: String? = "/tmp/img.jpg") = CameraFrame(
        frameId               = UUID.randomUUID().toString(),
        timestampMs           = System.currentTimeMillis(),
        width                 = 1280,
        height                = 960,
        rotationDegrees       = 0,
        imagePathOrBufferRef  = path,
    )

    private fun makeController(detector: MockTargetDetector): AutoCaptureController {
        val ctrl = AutoCaptureController(config = config, detector = detector)
        ctrl.onCameraStreaming()
        return ctrl
    }

    // 1. No candidate -> stays Searching; soft timeout is UI-only (no failure state)
    @Test
    fun `no candidate stays Searching even past soft timeout`() {
        val detector = MockTargetDetector.noCandidateForever()
        val ctrl = makeController(detector)
        assertEquals(AutoCaptureState.Searching, ctrl.state.value)

        val pastTimeout = System.currentTimeMillis() + config.searchTimeoutMs + 100
        repeat(20) { ctrl.processFrame(frame(), pastTimeout) }

        // Must still be Searching, NOT any error/rejected terminal state
        assertTrue(ctrl.state.value is AutoCaptureState.Searching)
    }

    // 2. Single-frame candidate noise -> does NOT enter Locking
    @Test
    fun `single frame candidate does not enter Locking`() {
        val detector = MockTargetDetector.singleFrameCandidate(box)
        val ctrl = makeController(detector)

        // First frame: candidate detected -> CandidateDetected
        ctrl.processFrame(frame())
        assertTrue(
            "Expected CandidateDetected after 1st frame, got ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.CandidateDetected,
        )

        // Second frame: no candidate -> back to Searching (never Locking)
        ctrl.processFrame(frame())
        assertFalse(
            "Must NOT enter Locking from single-frame noise",
            ctrl.state.value is AutoCaptureState.Locking,
        )
        assertTrue(ctrl.state.value is AutoCaptureState.Searching)
    }

    // 3. Candidate for 2 consecutive frames -> enters Locking
    @Test
    fun `two consecutive candidate frames enters Locking`() {
        val detector = MockTargetDetector.stableCandidate(100, box)
        val ctrl = makeController(detector)

        ctrl.processFrame(frame()) // -> CandidateDetected
        ctrl.processFrame(frame()) // -> Locking

        assertTrue(
            "Expected Locking after 2 consecutive frames, got ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Locking,
        )
    }

    // 4. N stable frames -> Locked -> Capturing -> Captured (MNN pending, no pass/fail)
    @Test
    fun `stable frames reach Locked then Captured with no pass_fail`() = runTest {
        val detector = MockTargetDetector.stableCandidate(config.requiredStableFrames + 10, box)
        var captureCallCount = 0
        val ctrl = AutoCaptureController(
            config   = config,
            detector = detector,
            captureHandler = { f, b ->
                captureCallCount++
                CapturedPhoto("id", "2026-01-01T00:00:00Z", f.imagePathOrBufferRef!!, f.frameId, b)
            },
        )
        ctrl.onCameraStreaming()

        // Drive through CandidateDetected -> Locking
        val f = frame()
        repeat(2) { ctrl.processFrame(f) }
        assertTrue(ctrl.state.value is AutoCaptureState.Locking)

        // Accumulate requiredStableFrames
        repeat(config.requiredStableFrames + 5) { ctrl.processFrame(f) }
        assertTrue(
            "Expected Locked, got ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Locked,
        )

        // Trigger capture
        val lockedBox = (ctrl.state.value as AutoCaptureState.Locked).box
        ctrl.triggerCapture(f, lockedBox)

        assertTrue(
            "Expected Captured, got ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Captured,
        )
        assertEquals(1, captureCallCount)
        // Result must NOT be pass/fail — photo handed off; MNN pending
        val photo = (ctrl.state.value as AutoCaptureState.Captured).capture
        assertNotNull(photo.captureId)
        assertNotNull(photo.rawImagePath)
    }

    // 5. Sudden move mid-Locking -> reset to Searching, stableFrameCount=0
    @Test
    fun `position move mid-Locking resets to Searching`() {
        val detector = MockTargetDetector.candidateThenMove(stableCount = 4, box = box)
        val ctrl = makeController(detector)

        // Enter Locking
        repeat(2) { ctrl.processFrame(frame()) }
        assertTrue(ctrl.state.value is AutoCaptureState.Locking)

        // A few more stable frames
        repeat(2) { ctrl.processFrame(frame()) }
        // Then moved box frames from detector
        repeat(10) { ctrl.processFrame(frame()) }

        assertTrue(
            "Expected Searching after position move, got ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Searching,
        )
    }

    // 6. One bad-quality frame mid-Locking then recovery -> no reset, keeps accumulating
    @Test
    fun `one bad quality frame within tolerance does not reset`() {
        val totalFrames = config.requiredStableFrames + 10
        val detector = MockTargetDetector.stableWithOneBadQualityFrame(
            totalCount = totalFrames,
            badAt      = 4, // bad frame at index 4 (within tolerance of 2)
            box        = box,
        )
        val ctrl = makeController(detector)

        // Enter Locking (2 frames)
        repeat(2) { ctrl.processFrame(frame()) }
        assertTrue(ctrl.state.value is AutoCaptureState.Locking)

        // Drive more frames including the bad-quality one
        repeat(totalFrames) { ctrl.processFrame(frame()) }

        // Should have reached Locked (not reset to Searching)
        assertFalse(
            "Must not reset to Searching on single quality fail within tolerance",
            ctrl.state.value is AutoCaptureState.Searching,
        )
        assertTrue(
            "Expected Locked after recovery, got ${ctrl.state.value}",
            ctrl.state.value is AutoCaptureState.Locked,
        )
    }

    // 7. Quality fails beyond tolerance -> reset to Searching
    @Test
    fun `persistent bad quality beyond tolerance resets to Searching`() {
        val detector = MockTargetDetector.persistentBadQuality(count = 100, box = box)
        val ctrl = makeController(detector)

        // Enter Locking (2 good frames using a separate stableCandidate sequence to bootstrap)
        val bootstrap = MockTargetDetector.stableCandidate(2, box)
        val bootstrapCtrl = AutoCaptureController(config = config, detector = bootstrap)
        bootstrapCtrl.onCameraStreaming()
        repeat(2) { bootstrapCtrl.processFrame(frame()) }
        // now simulate: switch to persistent bad quality by using full detector on fresh controller
        // Use stableWithOneBadQualityFrame with badAt=2 and qualityFail > tolerance
        val seq = buildList {
            repeat(2) { add(TargetDetection(true, 0.9f, box, FrameQuality.GOOD)) }   // enter Locking
            repeat(config.qualityFailToleranceFrames + 3) {                            // exceed tolerance
                add(TargetDetection(true, 0.9f, box, FrameQuality.BAD))
            }
        }
        val det2 = MockTargetDetector(seq)
        val ctrl2 = AutoCaptureController(config = config, detector = det2)
        ctrl2.onCameraStreaming()

        repeat(2) { ctrl2.processFrame(frame()) } // enter Locking
        assertTrue(ctrl2.state.value is AutoCaptureState.Locking)

        repeat(config.qualityFailToleranceFrames + 3) { ctrl2.processFrame(frame()) }
        assertTrue(
            "Expected Searching after quality tolerance exceeded, got ${ctrl2.state.value}",
            ctrl2.state.value is AutoCaptureState.Searching,
        )
    }

    // 8. Never reaches N within lockingTimeoutMs -> Rejected(LOCKING_TIMEOUT)
    @Test
    fun `locking timeout produces Rejected LOCKING_TIMEOUT`() {
        val detector = MockTargetDetector.stableCandidate(count = 1000, box = box)
        val ctrl = makeController(detector)

        // Enter Locking
        repeat(2) { ctrl.processFrame(frame()) }
        assertTrue(ctrl.state.value is AutoCaptureState.Locking)

        // Drive frames with nowMs past lockingTimeoutMs
        val expiredMs = System.currentTimeMillis() + config.lockingTimeoutMs + 100
        ctrl.processFrame(frame(), expiredMs)

        assertEquals(
            AutoCaptureState.Rejected(RejectReason.LOCKING_TIMEOUT),
            ctrl.state.value,
        )
    }

    // 9. Within captureDebounceMs after Captured, new candidate does NOT re-trigger Locking
    @Test
    fun `new candidate during debounce does not re-trigger Locking`() = runTest {
        val detector = MockTargetDetector.stableCandidate(config.requiredStableFrames + 20, box)
        val ctrl = AutoCaptureController(
            config   = config,
            detector = detector,
            captureHandler = { f, b ->
                CapturedPhoto("id", "2026T", f.imagePathOrBufferRef!!, f.frameId, b)
            },
        )
        ctrl.onCameraStreaming()

        // Reach Locked
        val f = frame()
        repeat(2 + config.requiredStableFrames + 2) { ctrl.processFrame(f) }
        val locked = ctrl.state.value
        assertTrue("Expected Locked, got $locked", locked is AutoCaptureState.Locked)

        ctrl.triggerCapture(f, (locked as AutoCaptureState.Locked).box)
        assertTrue(ctrl.state.value is AutoCaptureState.Captured)

        // While in debounce, push frames with strong candidates
        repeat(10) { ctrl.processFrame(f) }

        // Must stay Captured during debounce (isInDebounce=true)
        assertTrue(ctrl.isInDebounce())
        assertFalse(
            "Must not re-enter Locking during debounce",
            ctrl.state.value is AutoCaptureState.Locking,
        )
        assertTrue(ctrl.state.value is AutoCaptureState.Captured)
    }

    // 10. Capture throws IO error -> Rejected(CAPTURE_IO_ERROR), no crash
    @Test
    fun `capture IO error produces Rejected CAPTURE_IO_ERROR`() = runTest {
        val detector = MockTargetDetector.stableCandidate(config.requiredStableFrames + 20, box)
        val ctrl = AutoCaptureController(
            config   = config,
            detector = detector,
            captureHandler = { _, _ -> throw RuntimeException("disk full") },
        )
        ctrl.onCameraStreaming()

        val f = frame()
        repeat(2 + config.requiredStableFrames + 2) { ctrl.processFrame(f) }
        assertTrue(ctrl.state.value is AutoCaptureState.Locked)

        ctrl.triggerCapture(f, (ctrl.state.value as AutoCaptureState.Locked).box)

        assertEquals(
            AutoCaptureState.Rejected(RejectReason.CAPTURE_IO_ERROR),
            ctrl.state.value,
        )
    }
}
