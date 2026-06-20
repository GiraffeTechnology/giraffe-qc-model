package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

/**
 * Lightweight target-presence detector for live frames.
 * NEVER produces QC pass/fail. Only signals whether a frame is a good capture candidate.
 */
interface TargetDetector {
    fun detect(frame: CameraFrame): TargetDetection
}
