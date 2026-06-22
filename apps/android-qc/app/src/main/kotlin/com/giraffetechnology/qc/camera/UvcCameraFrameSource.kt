package com.giraffetechnology.qc.camera

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

class UvcCameraFrameSource : CameraFrameSource {
    private val _frames = MutableSharedFlow<CameraFrame>(extraBufferCapacity = 4)
    override val frames: Flow<CameraFrame> = _frames.asSharedFlow()

    override fun start() {
        // CameraX / UVC initialisation wired at device integration time
    }

    override fun stop() {
        // Release camera resources
    }
}
