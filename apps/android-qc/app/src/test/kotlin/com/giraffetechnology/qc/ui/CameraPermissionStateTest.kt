package com.giraffetechnology.qc.ui

import org.junit.Assert.*
import org.junit.Test

/**
 * Unit tests for camera permission state logic.
 * CameraPreviewPane must not be composed (and bind() must not be called) unless
 * CameraPermissionState is Granted.
 */
class CameraPermissionStateTest {

    @Test
    fun `Checking is the initial state before permission is inspected`() {
        val initial = CameraPermissionState.Checking
        assertNotEquals(CameraPermissionState.Granted, initial)
        assertNotEquals(CameraPermissionState.Denied, initial)
    }

    @Test
    fun `isGranted true resolves to Granted`() {
        assertEquals(CameraPermissionState.Granted, resolvePermissionState(true))
    }

    @Test
    fun `isGranted false resolves to Denied`() {
        assertEquals(CameraPermissionState.Denied, resolvePermissionState(false))
    }

    @Test
    fun `only Granted enables manual capture when camera is also ready`() {
        fun captureEnabled(perm: CameraPermissionState, cameraReady: Boolean) =
            cameraReady && perm == CameraPermissionState.Granted

        assertTrue(captureEnabled(CameraPermissionState.Granted, true))
        assertFalse("Checking blocks capture", captureEnabled(CameraPermissionState.Checking, true))
        assertFalse("Denied blocks capture", captureEnabled(CameraPermissionState.Denied, true))
        assertFalse("Granted but not ready blocks capture",
            captureEnabled(CameraPermissionState.Granted, false))
    }
}
