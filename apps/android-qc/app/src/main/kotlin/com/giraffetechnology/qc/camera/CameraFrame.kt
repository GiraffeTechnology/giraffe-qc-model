package com.giraffetechnology.qc.camera

/**
 * A single captured camera frame.
 *
 * [imagePathOrBufferRef] is either a file path written to disk or a buffer
 * reference token, depending on the capture pipeline stage. It is null when
 * the frame has not yet been persisted (e.g. during live preview analysis).
 */
data class CameraFrame(
    val frameId: String,
    val timestampMs: Long,
    val imagePathOrBufferRef: String?,
    val widthPx: Int,
    val heightPx: Int,
)
