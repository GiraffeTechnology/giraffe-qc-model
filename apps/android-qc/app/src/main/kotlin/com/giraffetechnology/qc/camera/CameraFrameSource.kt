package com.giraffetechnology.qc.camera

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

interface CameraFrameSource {
    val state: StateFlow<CameraState>
    val frames: Flow<CameraFrame>
    suspend fun start()
    suspend fun stop()
}
