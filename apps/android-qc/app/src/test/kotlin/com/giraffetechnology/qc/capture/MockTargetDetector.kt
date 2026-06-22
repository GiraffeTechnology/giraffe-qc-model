package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

class MockTargetDetector(
    private var next: TargetDetection = TargetDetection(
        hasCandidate = false,
        confidence = 0f,
        boundingBox = null,
        quality = FrameQuality.GOOD,
    )
) : TargetDetector {
    var callCount = 0
        private set

    fun setNext(detection: TargetDetection) { next = detection }

    override fun detect(frame: CameraFrame): TargetDetection {
        callCount++
        return next
    }
}
