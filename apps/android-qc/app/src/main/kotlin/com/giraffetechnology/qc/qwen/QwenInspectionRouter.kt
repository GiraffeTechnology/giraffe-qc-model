package com.giraffetechnology.qc.qwen

import android.util.Log
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout

/**
 * Android Pad local-only inspection router.
 *
 * Cloud fallback is PERMANENTLY DISABLED on the android-pad-app branch.
 * The router calls only on-device MNN inference. No exception.
 *
 * Decision flow:
 *   local MNN pass (confidence >= threshold)  → pass
 *   local MNN fail                            → fail (final, no escalation)
 *   local MNN review_required                 → review_required
 *   model missing / MNN missing               → review_required
 *   native inference not wired                → review_required
 *   JSON parse failure                        → review_required
 *   timeout                                   → review_required
 *   cloud fallback                            → FORBIDDEN
 *   Qwen API fallback                         → FORBIDDEN
 */
data class RouterConfig(
    val mode: String = "local_only",
    val onDeviceEnabled: Boolean = true,
    val onDeviceTimeoutMs: Long = 60_000L,
    val minConfidence: Float = 0.82f,
    val onDeviceFailIsFinal: Boolean = true,
    // Cloud fields retained for interface compatibility with tests that verify
    // the Pad router ignores them. Values are never acted on.
    val cloudEnabled: Boolean = false,
    val allowSendImages: Boolean = false,
)

class QwenInspectionRouter(
    private val onDeviceInspector: QwenInspector,
    // cloudInspector is accepted for interface compatibility but NEVER called on this branch.
    private val cloudInspector: QwenInspector? = null,
    private val config: RouterConfig = RouterConfig(),
) {
    companion object { private const val TAG = "QwenRouter" }

    suspend fun route(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        if (!config.onDeviceEnabled) {
            return makeReviewRequired(qcPoints, "on_device_disabled")
        }

        val onDeviceResult = tryOnDevice(standardPhotos, capturedPhoto, qcPoints, context)
            ?: return makeReviewRequired(qcPoints, "on_device_unavailable")

        // Fail is final — no cloud escalation permitted
        if (onDeviceResult.overallResult == "fail" && config.onDeviceFailIsFinal) {
            Log.d(TAG, "On-device FAIL is final — cloud escalation forbidden (Pad local-only)")
            return onDeviceResult
        }

        if (isAcceptable(onDeviceResult)) {
            Log.d(TAG, "On-device result accepted: ${onDeviceResult.overallResult}")
            return onDeviceResult
        }

        // Not acceptable → review_required. Cloud fallback is forbidden.
        val reason = when (onDeviceResult.overallResult) {
            "review_required" -> "on_device_review_required"
            else              -> "on_device_confidence_below_threshold"
        }
        Log.d(TAG, "Result not acceptable ($reason) — review_required (cloud fallback forbidden)")
        return makeReviewRequired(qcPoints, reason)
    }

    private suspend fun tryOnDevice(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput? {
        return try {
            withTimeout(config.onDeviceTimeoutMs) {
                onDeviceInspector.inspect(standardPhotos, capturedPhoto, qcPoints, context)
            }
        } catch (e: TimeoutCancellationException) {
            Log.w(TAG, "On-device timeout after ${config.onDeviceTimeoutMs}ms → review_required")
            null
        } catch (e: UnsupportedOperationException) {
            Log.w(TAG, "On-device not available: ${e.message} → review_required")
            null
        } catch (e: Exception) {
            Log.w(TAG, "On-device error: ${e.message} → review_required")
            null
        }
    }

    private fun isAcceptable(result: QwenInspectionOutput): Boolean {
        if (result.overallResult !in setOf("pass", "fail", "review_required")) return false
        if (result.items.isEmpty()) return false
        if (result.confidence < config.minConfidence) return false
        if (result.overallResult == "review_required") return false
        return true
    }

    private fun makeReviewRequired(qcPoints: List<QcPointInput>, reason: String) =
        QwenInspectionOutput(
            overallResult = "review_required",
            engine        = "router",
            modelName     = "none",
            confidence    = 0.0f,
            items         = qcPoints.map { p ->
                InspectionItemResult(p.qcPointId, p.qcPointCode, p.name,
                    "review_required", 0.0f, reason)
            },
            fallback = FallbackInfo(used = false, reason = reason),
            summary  = "Deferred: $reason",
        )
}
