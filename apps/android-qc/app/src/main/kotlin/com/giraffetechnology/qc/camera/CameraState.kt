package com.giraffetechnology.qc.camera

sealed class CameraState {
    data object Disconnected : CameraState()
    data object PermissionRequired : CameraState()
    data object Connecting : CameraState()
    data object Streaming : CameraState()
    data class Error(val reason: String) : CameraState()
}
