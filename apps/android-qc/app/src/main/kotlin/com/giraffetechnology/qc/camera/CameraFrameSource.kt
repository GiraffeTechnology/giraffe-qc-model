package com.giraffetechnology.qc.camera

import kotlinx.coroutines.flow.Flow

interface CameraFrameSource {
    val frames: Flow<CameraFrame>
    fun start()
    fun stop()
}
