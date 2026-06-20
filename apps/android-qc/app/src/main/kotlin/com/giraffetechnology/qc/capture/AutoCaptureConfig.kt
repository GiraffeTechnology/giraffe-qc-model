package com.giraffetechnology.qc.capture

data class AutoCaptureConfig(
    val requiredStableFrames: Int = 10,
    val maxCenterDriftRatio: Float = 0.05f,
    val maxAreaChangeRatio: Float = 0.10f,
    val minConfidence: Float = 0.6f,
    val searchTimeoutMs: Long = 8_000L,
    val lockingTimeoutMs: Long = 5_000L,
    val captureDebounceMs: Long = 1_500L,
    val qualityFailToleranceFrames: Int = 2,
)
