package com.giraffetechnology.qc.camera

import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import java.util.UUID

class MockCameraFrameSource(
    private val frameWidth: Int = 1280,
    private val frameHeight: Int = 960,
) : CameraFrameSource {

    private val _state = MutableStateFlow<CameraState>(CameraState.Disconnected)
    override val state: StateFlow<CameraState> = _state.asStateFlow()

    private val _frames = MutableSharedFlow<CameraFrame>(extraBufferCapacity = 16)
    override val frames: Flow<CameraFrame> = _frames.asSharedFlow()

    override suspend fun start() {
        _state.value = CameraState.Connecting
        delay(50)
        _state.value = CameraState.Streaming
    }

    override suspend fun stop() {
        _state.value = CameraState.Disconnected
    }

    suspend fun emitFrame(path: String? = null): CameraFrame {
        val frame = CameraFrame(
            frameId = UUID.randomUUID().toString(),
            timestampMs = System.currentTimeMillis(),
            width = frameWidth,
            height = frameHeight,
            rotationDegrees = 0,
            imagePathOrBufferRef = path,
        )
        _frames.emit(frame)
        return frame
    }

    fun simulateDisconnect() {
        _state.value = CameraState.Error("simulated disconnect")
    }

    fun simulateStreaming() {
        _state.value = CameraState.Streaming
    }
}
