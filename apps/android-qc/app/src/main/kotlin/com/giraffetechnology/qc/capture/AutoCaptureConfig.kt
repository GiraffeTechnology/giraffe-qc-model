package com.giraffetechnology.qc.capture

data class AutoCaptureConfig(
    /** Number of consecutive stable frames required before declaring Locked. */
    val requiredStableFrames: Int = 8,
    /** Maximum centre-point drift (normalised) between consecutive frames in Locking. */
    val maxCenterDriftRatio: Float = 0.05f,
    /** Maximum bounding-box area change ratio between consecutive frames in Locking. */
    val maxAreaChangeRatio: Float = 0.10f,
    /** Minimum detector confidence to count a frame as a candidate. */
    val minConfidence: Float = 0.6f,
    /** Time (ms) before the Searching state gives up waiting for a target (informational). */
    val searchTimeoutMs: Long = 10_000L,
    /** Time (ms) after entering Locking before declaring LOCKING_TIMEOUT. */
    val lockingTimeoutMs: Long = 3_000L,
    /** Time (ms) to ignore new capture triggers after a successful capture. */
    val captureDebounceMs: Long = 2_000L,
    /** How many consecutive low-quality frames are tolerated in Locking before resetting. */
    val qualityFailToleranceFrames: Int = 3,
)
