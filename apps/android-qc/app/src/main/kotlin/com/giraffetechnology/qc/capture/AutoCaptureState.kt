package com.giraffetechnology.qc.capture

sealed class AutoCaptureState {
    data object Idle : AutoCaptureState()
    data object Searching : AutoCaptureState()
    data class CandidateDetected(val box: NormalizedBox) : AutoCaptureState()
    data class Locking(val stableFrameCount: Int, val requiredFrameCount: Int) : AutoCaptureState()
    data class Locked(val box: NormalizedBox) : AutoCaptureState()
    data class Capturing(val box: NormalizedBox) : AutoCaptureState()
    data class Captured(val capture: CapturedPhoto) : AutoCaptureState()
    data class Rejected(val reason: RejectReason) : AutoCaptureState()
}

enum class RejectReason {
    LOCKING_TIMEOUT,
    CAPTURE_IO_ERROR,
    CAMERA_DISCONNECTED,
    USER_CANCELLED,
}
