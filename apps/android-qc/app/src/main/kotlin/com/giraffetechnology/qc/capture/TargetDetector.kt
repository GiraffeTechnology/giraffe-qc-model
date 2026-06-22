package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame

/**
 * Normalised bounding box in [0, 1] coordinate space.
 * (cx, cy) is the box centre; (w, h) is width and height.
 */
data class NormalizedBox(
    val cx: Float,
    val cy: Float,
    val w: Float,
    val h: Float,
)

enum class FrameQuality { GOOD, BLURRY, OVEREXPOSED, UNDEREXPOSED }

data class TargetDetection(
    val hasCandidate: Boolean,
    val confidence: Float,
    val boundingBox: NormalizedBox?,
    val quality: FrameQuality,
    val reason: String = "",
)

interface TargetDetector {
    fun detect(frame: CameraFrame): TargetDetection
}
