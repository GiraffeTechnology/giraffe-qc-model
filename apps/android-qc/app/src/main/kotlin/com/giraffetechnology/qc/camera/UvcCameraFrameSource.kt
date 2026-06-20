package com.giraffetechnology.qc.camera

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.*

/**
 * Real UVC camera integration stub.
 * Physical UVC hardware not yet available; stays Disconnected until implemented.
 * All QC frame capture uses MockCameraFrameSource during development.
 */
class UvcCameraFrameSource(
    @Suppress("UnusedPrivateProperty") private val context: Context,
) : CameraFrameSource {

    companion object { private const val TAG = "UvcCameraFrameSource" }

    private val _state = MutableStateFlow<CameraState>(CameraState.Disconnected)
    override val state: StateFlow<CameraState> = _state.asStateFlow()

    private val _frames = MutableSharedFlow<CameraFrame>(extraBufferCapacity = 16)
    override val frames: Flow<CameraFrame> = _frames.asSharedFlow()

    override suspend fun start() {
        Log.i(TAG, "UVC start — physical hardware pending; state=Disconnected")
        _state.value = CameraState.Disconnected
    }

    override suspend fun stop() {
        _state.value = CameraState.Disconnected
    }
}
