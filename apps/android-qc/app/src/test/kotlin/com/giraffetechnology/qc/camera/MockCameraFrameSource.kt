package com.giraffetechnology.qc.camera

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow

class MockCameraFrameSource : CameraFrameSource {
    private val _frames = MutableSharedFlow<CameraFrame>(extraBufferCapacity = 64)
    override val frames: Flow<CameraFrame> = _frames.asSharedFlow()

    override fun start() {}
    override fun stop() {}

    suspend fun emit(frame: CameraFrame) = _frames.emit(frame)
}
