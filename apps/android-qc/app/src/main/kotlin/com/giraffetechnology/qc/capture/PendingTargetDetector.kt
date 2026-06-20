package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

/** Production placeholder: hardware detector not yet connected. Always returns no-candidate. */
class PendingTargetDetector : TargetDetector {
    override fun detect(frame: CameraFrame): TargetDetection = TargetDetection(
        hasCandidate = false,
        confidence   = 0f,
        boundingBox  = null,
        quality      = FrameQuality.GOOD,
        reason       = "hardware_pending",
    )
}
