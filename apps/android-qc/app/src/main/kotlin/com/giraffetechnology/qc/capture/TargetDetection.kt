package com.giraffetechnology.qc.capture

data class NormalizedBox(
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float,
) {
    val centerX: Float get() = x + width / 2f
    val centerY: Float get() = y + height / 2f
    val area: Float get() = width * height

    companion object {
        val DEFAULT = NormalizedBox(0.3f, 0.3f, 0.4f, 0.4f)
    }
}

data class FrameQuality(
    val blurOk: Boolean,
    val exposureOk: Boolean,
    val centeredOk: Boolean,
    val sizeOk: Boolean,
    val glareOk: Boolean,
) {
    val allOk: Boolean get() = blurOk && exposureOk && centeredOk && sizeOk && glareOk

    companion object {
        val GOOD = FrameQuality(blurOk = true, exposureOk = true, centeredOk = true, sizeOk = true, glareOk = true)
        val BAD  = FrameQuality(blurOk = false, exposureOk = true, centeredOk = true, sizeOk = true, glareOk = true)
    }
}

data class TargetDetection(
    val hasCandidate: Boolean,
    val confidence: Float,
    val boundingBox: NormalizedBox?,
    val quality: FrameQuality,
    val reason: String? = null,
)
