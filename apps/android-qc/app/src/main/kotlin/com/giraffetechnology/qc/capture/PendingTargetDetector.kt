package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

class PendingTargetDetector : TargetDetector {
    override fun detect(frame: CameraFrame): TargetDetection =
        TargetDetection(
            hasCandidate = false,
            confidence   = 0f,
            boundingBox  = null,
            quality      = FrameQuality.GOOD,
            reason       = "MNN pending",
        )
}
