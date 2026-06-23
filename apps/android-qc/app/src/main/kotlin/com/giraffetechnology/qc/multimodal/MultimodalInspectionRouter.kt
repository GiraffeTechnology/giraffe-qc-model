package com.giraffetechnology.qc.multimodal

import android.util.Log
import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.FallbackInfo
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.InspectionItemResult
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout

/**
 * Provider-neutral inspection router for the Android Pad.
 *
 * Selection order:
 *   1. MockInspector      — config.mockEnabled (CI/test)
 *   2. LocalMnnInspector  — config.localMnnEnabled (default primary)
 *   3. BackendProxyInspector — config.backendProxyEnabled (opt-in)
 *
 * Cloud providers are never called from the Pad; config.directCloudEnabled is always false.
 *
 * On-device fail is final: a clear "fail" from LocalMnn is not escalated to backendProxy.
 * A review_required or low-confidence result may fall through to backendProxy if enabled.
 */
class MultimodalInspectionRouter(
    private val config: MultimodalProviderConfig,
    private val localMnn: MultimodalInspector? = null,
    private val backendProxy: MultimodalInspector? = null,
    private val mock: MultimodalInspector? = null,
) {
    companion object {
        private const val TAG = "MultimodalRouter"
    }

    suspend fun route(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        if (config.mockEnabled) {
            val inspector = mock ?: MockInspector()
            Log.d(TAG, "Mock mode — using ${inspector.inspectorName}")
            return inspector.inspect(standardPhotos, capturedPhoto, qcPoints, context)
        }

        if (config.localMnnEnabled) {
            val result = tryInspect(
                localMnn, standardPhotos, capturedPhoto, qcPoints, context,
                "local_mnn_unavailable",
            )
            if (result != null) {
                if (result.overallResult == "fail") {
                    // Fail is final — on-device defect detection is authoritative
                    Log.d(TAG, "LocalMNN FAIL is final, no escalation to backend proxy")
                    return result
                }
                if (result.overallResult != "review_required" &&
                    result.confidence >= config.minPassConfidence) {
                    Log.d(TAG, "LocalMNN accepted: ${result.overallResult} conf=${result.confidence}")
                    return result
                }
                Log.d(TAG, "LocalMNN result not accepted: ${result.overallResult} conf=${result.confidence}")
            }
        }

        if (config.backendProxyEnabled) {
            Log.d(TAG, "Trying backend proxy")
            val result = tryInspect(
                backendProxy, standardPhotos, capturedPhoto, qcPoints, context,
                "backend_proxy_unavailable",
            )
            if (result != null) return result
        }

        Log.w(TAG, "No provider returned a result — review_required (no_provider_available)")
        return makeReviewRequired(qcPoints, "no_provider_available")
    }

    private suspend fun tryInspect(
        inspector: MultimodalInspector?,
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
        unavailableReason: String,
    ): QwenInspectionOutput? {
        if (inspector == null) {
            Log.d(TAG, "$unavailableReason — not configured")
            return null
        }
        return try {
            withTimeout(config.onDeviceTimeoutMs) {
                inspector.inspect(standardPhotos, capturedPhoto, qcPoints, context)
            }
        } catch (e: TimeoutCancellationException) {
            Log.w(TAG, "${inspector.inspectorName} timeout after ${config.onDeviceTimeoutMs}ms")
            null
        } catch (e: UnsupportedOperationException) {
            Log.w(TAG, "${inspector.inspectorName} not provisioned: ${e.message}")
            null
        } catch (e: Exception) {
            Log.w(TAG, "${inspector.inspectorName} error: ${e.message}")
            null
        }
    }

    private fun makeReviewRequired(qcPoints: List<QcPointInput>, reason: String) =
        QwenInspectionOutput(
            overallResult = "review_required",
            engine        = "multimodal_router",
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
