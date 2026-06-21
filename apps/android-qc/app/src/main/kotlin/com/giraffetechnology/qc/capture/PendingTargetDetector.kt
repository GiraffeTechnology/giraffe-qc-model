package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

/**
 * Production-safe placeholder TargetDetector used while the MNN visual
 * model is not yet provisioned on the device.
 *
 * Always returns hasCandidate=false with reason="MNN pending" so the
 * capture state machine stays in Searching without emitting a fake result.
 */
class PendingTargetDetector : TargetDetector {
    override fun detect(frame: CameraFrame): TargetDetection =
        TargetDetection(
            hasCandidate = false,
            confidence = 0f,
            boundingBox = null,
            quality = FrameQuality.GOOD,
            reason = "MNN pending",
        )
}
