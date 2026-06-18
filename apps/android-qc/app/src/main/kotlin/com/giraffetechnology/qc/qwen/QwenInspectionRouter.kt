package com.giraffetechnology.qc.qwen

import android.util.Log
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout

/**
 * On-device inspection router (§4.5.1).
 *
 * Decision flow:
 *   run on_device_qwen (MNN)
 *     → if valid and confident: accept
 *     → else: check fallback policy
 *         → if cloud allowed: call cloud
 *         → else: return review_required
 *
 * §4.5.4: on-device FAIL is final — never escalate to cloud to produce a pass.
 * §1.5: uncertain cases become review_required, never pass.
 */
data class RouterConfig(
    val mode: String = "on_device_first",
    val onDeviceEnabled: Boolean = true,
    val onDeviceTimeoutMs: Long = 10_000L,
    val cloudEnabled: Boolean = false,
    val requireUserConsent: Boolean = true,
    val allowSendImages: Boolean = false,
    val minConfidence: Float = 0.82f,
    val onDeviceFailIsFinal: Boolean = true,
)

class QwenInspectionRouter(
    private val onDeviceInspector: QwenInspector,
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

        // Try on-device
        val onDeviceResult = tryOnDevice(standardPhotos, capturedPhoto, qcPoints, context)
            ?: return makeReviewRequired(qcPoints, "on_device_unavailable")

        // §4.5.4: fail is final
        if (onDeviceResult.overallResult == "fail" && config.onDeviceFailIsFinal) {
            Log.d(TAG, "On-device FAIL is final per §4.5.4")
            return onDeviceResult
        }

        // Accept if meets quality bar
        if (isAcceptable(onDeviceResult)) {
            Log.d(TAG, "On-device result accepted: ${onDeviceResult.overallResult}")
            return onDeviceResult
        }

        // Fallback
        val fallbackReason = when (onDeviceResult.overallResult) {
            "review_required" -> "on_device_review_required"
            else              -> "on_device_confidence_below_threshold"
        }
        return handleFallback(standardPhotos, capturedPhoto, qcPoints, context, fallbackReason)
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
            Log.w(TAG, "On-device timeout after ${config.onDeviceTimeoutMs}ms")
            handleFallback(standardPhotos, capturedPhoto, qcPoints, context, "on_device_timeout")
            null
        } catch (e: UnsupportedOperationException) {
            val reason = if (e.message?.contains("not_provisioned") == true)
                "on_device_model_not_provisioned" else "on_device_unsupported"
            Log.w(TAG, "On-device error ($reason): ${e.message}")
            handleFallback(standardPhotos, capturedPhoto, qcPoints, context, reason)
            null
        } catch (e: Exception) {
            Log.w(TAG, "On-device error: ${e.message}")
            handleFallback(standardPhotos, capturedPhoto, qcPoints, context, "on_device_error")
            null
        }
    }

    private suspend fun handleFallback(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
        reason: String,
    ): QwenInspectionOutput {
        if (!config.cloudEnabled || cloudInspector == null) {
            Log.d(TAG, "Cloud disabled — review_required ($reason)")
            return makeReviewRequired(qcPoints, reason)
        }
        return try {
            Log.d(TAG, "Cloud fallback triggered: $reason")
            val result = cloudInspector.inspect(standardPhotos, capturedPhoto, qcPoints, context)
            result.copy(fallback = FallbackInfo(used = true, reason = reason))
        } catch (e: Exception) {
            Log.w(TAG, "Cloud fallback also failed: ${e.message}")
            makeReviewRequired(qcPoints, "cloud_fallback_also_failed")
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
            fallback = FallbackInfo(used = true, reason = reason),
            summary  = "Deferred: $reason",
        )
}
