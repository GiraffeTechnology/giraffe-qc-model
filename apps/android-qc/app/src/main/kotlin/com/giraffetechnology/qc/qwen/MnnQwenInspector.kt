package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * On-device Qwen3-VL-4B-Instruct-MNN inspector backed by local MNN inference.
 *
 * Target: Android Pad (Snapdragon, 8+ GB RAM). Model: Qwen3-VL-4B-Instruct-MNN.
 *
 * When MNN AAR is not present or model files are incomplete:
 *   inspect() returns review_required — NEVER throws, NEVER calls cloud.
 *
 * When nativeRunInference() is wired (MNN AAR integrated):
 *   Replace the scaffold block with the real JNI call below.
 *
 * enable_thinking is set to false in the prompt; parser strips <think>...</think> if present.
 */
class MnnQwenInspector(
    private val context: Context,
    private val runtimeLoader: MnnRuntimeLoader,
    override val modelName: String = "Qwen3-VL-4B-Instruct-MNN",
) : QwenInspector {

    override val engineName: String = "local_qwen_mnn"

    companion object { private const val TAG = "MnnQwenInspector" }

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = withContext(Dispatchers.Default) {
        if (!runtimeLoader.isLoaded()) {
            Log.w(TAG, "Model not loaded — returning review_required (local_runtime_not_ready)")
            return@withContext makeReviewRequired(qcPoints, "local_runtime_not_ready")
        }

        val schemaExample = JSONObject().apply {
            put("overall_result", "pass | fail | review_required")
            put("confidence", 0.9)
            put("model_name", modelName)
            put("summary", "")
            put("items", org.json.JSONArray())
            put("fallback", JSONObject().apply {
                put("used", false); put("reason", JSONObject.NULL)
            })
        }.toString(2)

        val prompt = QcPromptBuilder.build(
            standardPhotos, capturedPhoto, qcPoints, schemaExample
        )
        val expectedIds = qcPoints.map { it.qcPointId }

        // Production JNI call — replace scaffold when MNN AAR is integrated:
        // val rawJson = nativeRunInference(
        //     runtimeLoader.modelPtr,
        //     buildImageInputJson(standardPhotos, capturedPhoto),
        //     prompt,   // includes enable_thinking=false directive
        // )
        // return@withContext QcResultParser.parse(rawJson, expectedIds, engineName)

        // Scaffold: native MNN not yet wired → review_required (never pass, never cloud)
        Log.w(TAG, "nativeRunInference not wired — returning review_required (native_inference_not_wired)")
        makeReviewRequired(qcPoints, "native_inference_not_wired")
    }

    private fun makeReviewRequired(qcPoints: List<QcPointInput>, reason: String) =
        QwenInspectionOutput(
            overallResult = "review_required",
            engine        = engineName,
            modelName     = modelName,
            confidence    = 0.0f,
            items         = qcPoints.map { p ->
                InspectionItemResult(
                    qcPointId   = p.qcPointId,
                    qcPointCode = p.qcPointCode,
                    name        = p.name,
                    result      = "review_required",
                    confidence  = 0.0f,
                    reason      = reason,
                )
            },
            fallback = FallbackInfo(used = false, reason = reason),
            summary  = "Local MNN not ready: $reason",
        )
}
