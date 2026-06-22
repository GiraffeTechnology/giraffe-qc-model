package com.giraffetechnology.qc.capture

import com.giraffetechnology.qc.camera.CameraFrame
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.abs

// ── State types ───────────────────────────────────────────────────────────────────────────────

sealed class AutoCaptureState {
    object Idle : AutoCaptureState()
    object Searching : AutoCaptureState()
    object CandidateDetected : AutoCaptureState()
    object Locking : AutoCaptureState()
    data class Locked(val box: NormalizedBox) : AutoCaptureState()
    object Capturing : AutoCaptureState()
    data class Captured(val capture: CapturedPhoto) : AutoCaptureState()
    data class Rejected(val reason: RejectReason) : AutoCaptureState()
}

enum class RejectReason { LOCKING_TIMEOUT, CAPTURE_IO_ERROR }

data class CapturedPhoto(
    val captureId: String,
    val timestamp: String,
    val rawImagePath: String,
    val frameId: String,
    val boundingBox: NormalizedBox,
)

// ── Controller ───────────────────────────────────────────────────────────────────────────────

/**
 * State machine that drives the auto-capture flow:
 *
 *   Idle → (onCameraStreaming) → Searching
 *        → (candidate detected) → CandidateDetected
 *        → (second stable frame) → Locking  [counts stable frames]
 *        → (requiredStableFrames met) → Locked
 *        → (triggerCapture) → Capturing → Captured | Rejected(CAPTURE_IO_ERROR)
 *
 * Locking exit conditions:
 *   - Timeout → Rejected(LOCKING_TIMEOUT)  (never Searching)
 *   - No candidate / null box → Searching   (item left frame)
 *   - Excessive drift → Searching
 *   - Bad quality > toleranceFrames → Searching
 *   - Bad quality within tolerance → frame skipped, stable count unchanged
 */
class AutoCaptureController(
    private val config: AutoCaptureConfig = AutoCaptureConfig(),
    private val detector: TargetDetector,
    private val captureHandler: (suspend (CameraFrame, NormalizedBox) -> CapturedPhoto)? = null,
) {
    private val _state = MutableStateFlow<AutoCaptureState>(AutoCaptureState.Idle)
    val state: StateFlow<AutoCaptureState> = _state.asStateFlow()

    private var stableCount = 0
    private var qualityFailCount = 0
    private var lockingStartMs = 0L
    private var lastBox: NormalizedBox? = null
    private var capturedAtMs = 0L

    fun onCameraStreaming() {
        _state.value = AutoCaptureState.Searching
    }

    fun processFrame(frame: CameraFrame, nowMs: Long = System.currentTimeMillis()) {
        when (_state.value) {
            is AutoCaptureState.Searching -> {
                val detection = detector.detect(frame)
                if (detection.hasCandidate
                    && detection.confidence >= config.minConfidence
                    && detection.quality == FrameQuality.GOOD) {
                    lastBox = detection.boundingBox
                    _state.value = AutoCaptureState.CandidateDetected
                }
            }

            is AutoCaptureState.CandidateDetected -> {
                val detection = detector.detect(frame)
                if (detection.hasCandidate
                    && detection.confidence >= config.minConfidence
                    && detection.quality == FrameQuality.GOOD) {
                    stableCount = 1
                    qualityFailCount = 0
                    lockingStartMs = nowMs
                    lastBox = detection.boundingBox
                    _state.value = AutoCaptureState.Locking
                } else {
                    lastBox = null
                    _state.value = AutoCaptureState.Searching
                }
            }

            is AutoCaptureState.Locking -> {
                // Timeout check is unconditional and takes priority.
                if (nowMs - lockingStartMs > config.lockingTimeoutMs) {
                    resetLockingState()
                    _state.value = AutoCaptureState.Rejected(RejectReason.LOCKING_TIMEOUT)
                    return
                }

                val detection = detector.detect(frame)

                // Guard: candidate gone or bounding box lost — item left frame during locking.
                // Counting a stable frame without a live candidate would lock on a stale target.
                if (!detection.hasCandidate || detection.boundingBox == null) {
                    resetLockingState()
                    _state.value = AutoCaptureState.Searching
                    return
                }

                // Quality gate.
                if (detection.quality != FrameQuality.GOOD) {
                    qualityFailCount++
                    if (qualityFailCount > config.qualityFailToleranceFrames) {
                        resetLockingState()
                        _state.value = AutoCaptureState.Searching
                    }
                    // Within tolerance: skip frame — don't count as stable, don't reset.
                    return
                }

                // Drift gate.
                val prev = lastBox
                val curr = detection.boundingBox
                if (prev != null && curr != null) {
                    val driftX = abs(curr.cx - prev.cx)
                    val driftY = abs(curr.cy - prev.cy)
                    val prevArea = prev.w * prev.h
                    val currArea = curr.w * curr.h
                    val areaChange = if (prevArea > 0f) abs(currArea - prevArea) / prevArea else 1f
                    if (driftX > config.maxCenterDriftRatio
                        || driftY > config.maxCenterDriftRatio
                        || areaChange > config.maxAreaChangeRatio) {
                        resetLockingState()
                        _state.value = AutoCaptureState.Searching
                        return
                    }
                }

                // Stable frame — advance counter.
                qualityFailCount = 0
                if (curr != null) lastBox = curr
                stableCount++
                if (stableCount >= config.requiredStableFrames) {
                    _state.value = AutoCaptureState.Locked(lastBox!!)
                }
            }

            is AutoCaptureState.Locked -> { /* no-op: triggerCapture drives the next transition */ }

            else -> { /* Idle, Capturing, Captured, Rejected: processFrame is a no-op */ }
        }
    }

    suspend fun triggerCapture(frame: CameraFrame, box: NormalizedBox) {
        _state.value = AutoCaptureState.Capturing
        val result = runCatching { captureHandler?.invoke(frame, box) }
        capturedAtMs = System.currentTimeMillis()
        val photo = result.getOrNull()
        _state.value = if (photo != null) {
            AutoCaptureState.Captured(photo)
        } else {
            AutoCaptureState.Rejected(RejectReason.CAPTURE_IO_ERROR)
        }
    }

    fun isInDebounce(nowMs: Long = System.currentTimeMillis()): Boolean =
        capturedAtMs > 0L && (nowMs - capturedAtMs) < config.captureDebounceMs

    private fun resetLockingState() {
        stableCount = 0
        qualityFailCount = 0
        lastBox = null
    }
}
