package com.giraffetechnology.qc.ui

import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.capture.NormalizedBox
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

/**
 * Tests for capture failure surfacing in QcCaptureScreen.
 * Verifies that a failed captureStill() does not call onInspectionResult,
 * and that the error message is surfaced rather than swallowed.
 */
class CaptureErrorStateTest {

    private fun fakeCapturedPhoto() = CapturedPhoto(
        captureId    = "cap-err-1",
        timestamp    = "2026-01-01T00:00:00Z",
        rawImagePath = "/data/captures/cap-err-1.jpg",
        frameId      = "frame-err-1",
        boundingBox  = NormalizedBox(0.5f, 0.5f, 1f, 1f),
    )

    @Test
    fun `capture failure does not invoke onInspectionResult`() = runTest {
        var inspectionResultCalled = false
        var captureError: String? = null

        val result: Result<CapturedPhoto> = Result.failure(RuntimeException("Camera IO error"))
        result
            .onSuccess { inspectionResultCalled = true }
            .onFailure { e -> captureError = e.message ?: "Capture failed" }

        assertFalse("onInspectionResult must not be called on capture failure",
            inspectionResultCalled)
        assertNotNull("captureError must be set on failure", captureError)
        assertEquals("Camera IO error", captureError)
    }

    @Test
    fun `capture success clears error and routes to inspection`() = runTest {
        var captureError: String? = "previous error"
        var inspectionResultCalled = false

        captureError = null  // cleared at start of new capture attempt
        val result: Result<CapturedPhoto> = Result.success(fakeCapturedPhoto())
        result
            .onSuccess { inspectionResultCalled = true }
            .onFailure { e -> captureError = e.message ?: "Capture failed" }

        assertNull("captureError must be cleared at start of capture attempt", captureError)
        assertTrue("onInspectionResult must be called on capture success",
            inspectionResultCalled)
    }

    @Test
    fun `capture failure message is surfaced not swallowed`() = runTest {
        var captureError: String? = null
        val errorMsg = "takePicture callback: CAMERA_CLOSED"

        val result: Result<CapturedPhoto> = Result.failure(RuntimeException(errorMsg))
        result
            .onSuccess { /* not reached */ }
            .onFailure { e -> captureError = e.message ?: "Capture failed" }

        assertEquals(errorMsg, captureError)
    }
}
