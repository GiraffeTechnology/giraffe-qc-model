package com.giraffetechnology.qc.camera

data class CameraFrame(
    val frameId: String,
    val timestampMs: Long,
    val width: Int,
    val height: Int,
    val rotationDegrees: Int,
    val imagePathOrBufferRef: String?,
)
