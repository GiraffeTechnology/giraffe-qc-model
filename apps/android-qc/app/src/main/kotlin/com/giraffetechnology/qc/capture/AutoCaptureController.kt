package com.giraffetechnology.qc.capture

import android.util.Log
import com.giraffetechnology.qc.camera.CameraFrame
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant
import java.util.UUID
import kotlin.math.abs

/**
 * Drives the auto-capture lock-on state machine.
 *
 * Call [processFrame] for every incoming camera frame.
 * Call [onCameraStreaming] when the camera reaches Streaming state.
 * Call [triggerCapture] once the state reaches Locked (pass the locked frame + box).
 * Call [afterDebounce] / [afterRejection] to resume the cycle.
 *
 * Emits NO QC pass/fail. After Captured the result is always MNN pending / review_required.
 */
class AutoCaptureController(
    val config: AutoCaptureConfig = AutoCaptureConfig(),
    private val detector: TargetDetector,
    private val captureHandler: suspend (CameraFrame, NormalizedBox) -> CapturedPhoto = ::defaultCapture,
) {
    companion object {
        private const val TAG = "AutoCaptureController"
        private const val CANDIDATE_CONFIRM_FRAMES = 2

        suspend fun defaultCapture(frame: CameraFrame, box: NormalizedBox): CapturedPhoto {
            val path = frame.imagePathOrBufferRef
                ?: throw IllegalStateException("frame has no imagePathOrBufferRef")
            return CapturedPhoto(
                captureId      = UUID.randomUUID().toString(),
                capturedAtUtc  = Instant.now().toString(),
                rawImagePath   = path,
                sourceFrameId  = frame.frameId,
                previewBox     = box,
            )
        }
    }

    private val _state = MutableStateFlow<AutoCaptureState>(AutoCaptureState.Idle)
    val state: StateFlow<AutoCaptureState> = _state.asStateFlow()

    private var candidateConsecutiveFrames = 0
    private var stableFrameCount          = 0
    private var referenceBox: NormalizedBox? = null
    private var qualityFailCount          = 0
    private var lockingStartMs            = 0L
    private var searchStartMs             = 0L
    private var capturedAtMs              = 0L
    private var searchTimeoutLogged       = false

    fun onCameraStreaming() {
        if (_state.value is AutoCaptureState.Idle) enterSearching()
    }

    fun processFrame(frame: CameraFrame, nowMs: Long = System.currentTimeMillis()) {
        when (_state.value) {
            is AutoCaptureState.Searching         -> handleSearching(frame, nowMs)
            is AutoCaptureState.CandidateDetected -> handleCandidateDetected(frame, nowMs)
            is AutoCaptureState.Locking           -> handleLocking(frame, nowMs)
            else                                  -> { /* Idle / Locked / Capturing / Captured / Rejected handled externally */ }
        }
    }

    suspend fun triggerCapture(frame: CameraFrame, lockedBox: NormalizedBox) {
        if (_state.value !is AutoCaptureState.Locked) return
        _state.value = AutoCaptureState.Capturing(lockedBox)
        try {
            val photo = captureHandler(frame, lockedBox)
            capturedAtMs = System.currentTimeMillis()
            _state.value = AutoCaptureState.Captured(photo)
            Log.i(TAG, "→ Captured id=${photo.captureId} — MNN pending / review_required")
        } catch (e: Exception) {
            val reason = if (e.message?.contains("camera", ignoreCase = true) == true)
                RejectReason.CAMERA_DISCONNECTED else RejectReason.CAPTURE_IO_ERROR
            Log.e(TAG, "Capture failed: ${e.message} → Rejected($reason)")
            _state.value = AutoCaptureState.Rejected(reason)
        }
    }

    fun isInDebounce(nowMs: Long = System.currentTimeMillis()): Boolean =
        _state.value is AutoCaptureState.Captured &&
        (nowMs - capturedAtMs) < config.captureDebounceMs

    fun afterDebounce() {
        if (_state.value is AutoCaptureState.Captured) enterSearching()
    }

    fun afterRejection() {
        if (_state.value is AutoCaptureState.Rejected) enterSearching()
    }

    // ── private helpers ────────────────────────────────────────────────────────

    private fun enterSearching() {
        candidateConsecutiveFrames = 0
        stableFrameCount           = 0
        referenceBox               = null
        qualityFailCount           = 0
        searchStartMs              = System.currentTimeMillis()
        searchTimeoutLogged        = false
        _state.value = AutoCaptureState.Searching
        Log.d(TAG, "→ Searching")
    }

    private fun handleSearching(frame: CameraFrame, nowMs: Long) {
        if (!searchTimeoutLogged && nowMs - searchStartMs > config.searchTimeoutMs) {
            Log.d(TAG, "Search soft timeout — no candidate yet (UI hint only)")
            searchTimeoutLogged = true
        }
        val det = detector.detect(frame)
        if (det.hasCandidate && det.confidence >= config.minConfidence) {
            candidateConsecutiveFrames = 1
            _state.value = AutoCaptureState.CandidateDetected(det.boundingBox!!)
            Log.d(TAG, "→ CandidateDetected")
        } else {
            candidateConsecutiveFrames = 0
        }
    }

    private fun handleCandidateDetected(frame: CameraFrame, nowMs: Long) {
        val det = detector.detect(frame)
        if (det.hasCandidate && det.confidence >= config.minConfidence) {
            candidateConsecutiveFrames++
            if (candidateConsecutiveFrames >= CANDIDATE_CONFIRM_FRAMES) {
                referenceBox   = det.boundingBox!!
                stableFrameCount = 1
                qualityFailCount = 0
                lockingStartMs   = nowMs
                _state.value = AutoCaptureState.Locking(1, config.requiredStableFrames)
                Log.d(TAG, "→ Locking")
            } else {
                _state.value = AutoCaptureState.CandidateDetected(det.boundingBox!!)
            }
        } else {
            candidateConsecutiveFrames = 0
            enterSearching()
            Log.d(TAG, "CandidateDetected: candidate lost → Searching")
        }
    }

    private fun handleLocking(frame: CameraFrame, nowMs: Long) {
        if (nowMs - lockingStartMs > config.lockingTimeoutMs) {
            Log.w(TAG, "Locking timeout → Rejected(LOCKING_TIMEOUT)")
            _state.value = AutoCaptureState.Rejected(RejectReason.LOCKING_TIMEOUT)
            return
        }

        val det = detector.detect(frame)
        val ref = referenceBox!!

        if (!det.hasCandidate) {
            Log.d(TAG, "Locking: target lost → Searching")
            enterSearching()
            return
        }

        val curr     = det.boundingBox!!
        val driftX   = abs(curr.centerX - ref.centerX)
        val driftY   = abs(curr.centerY - ref.centerY)
        val areaRef  = ref.area.coerceAtLeast(1e-6f)
        val areaChange = abs(curr.area - ref.area) / areaRef

        if (driftX > config.maxCenterDriftRatio || driftY > config.maxCenterDriftRatio || areaChange > config.maxAreaChangeRatio) {
            Log.d(TAG, "Locking: unstable (dX=$driftX dY=$driftY da=$areaChange) → Searching")
            enterSearching()
            return
        }

        if (!det.quality.allOk) {
            qualityFailCount++
            Log.d(TAG, "Locking: quality fail #$qualityFailCount / ${config.qualityFailToleranceFrames}")
            if (qualityFailCount > config.qualityFailToleranceFrames) {
                Log.d(TAG, "Quality tolerance exceeded → Searching")
                enterSearching()
            } else {
                _state.value = AutoCaptureState.Locking(stableFrameCount, config.requiredStableFrames)
            }
            return
        }

        qualityFailCount = 0
        stableFrameCount++
        referenceBox = curr

        if (stableFrameCount >= config.requiredStableFrames) {
            Log.d(TAG, "→ Locked after $stableFrameCount stable frames")
            _state.value = AutoCaptureState.Locked(curr)
        } else {
            _state.value = AutoCaptureState.Locking(stableFrameCount, config.requiredStableFrames)
        }
    }
}
