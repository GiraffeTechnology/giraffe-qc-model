package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

/**
 * On-device inspector: routes VL inference through NativeMnnQwenBridge -> MNN LLM runtime.
 *
 * - Calls nativeRunInference() when model handle is non-zero.
 * - Returns review_required if handle is zero, output is blank, or any exception occurs.
 * - Never calls cloud, never calls DashScope, never returns pass from a failure path.
 * - [lastRawOutputLength] is updated after each nativeRunInference call; -1 if not yet called.
 */
class MnnQwenInspector(
    @Suppress("UnusedPrivateProperty") private val context: Context,
    private val runtimeLoader: MnnRuntimeLoader,
    override val modelName: String = "Qwen3-VL-4B-Instruct-MNN",
) : QwenInspector {

    override val engineName: String = "local_qwen_mnn"

    var lastRawOutputLength: Int = -1
        private set

    companion object {
        private const val TAG = "MnnQwenInspector"

        private val INFERENCE_PARAMS = JSONObject().apply {
            put("max_new_tokens", 1024)
            put("temperature", 0.1)
            put("do_sample", false)
            put("enable_thinking", false)
        }.toString()
    }

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = withContext(Dispatchers.Default) {
        val ptr = runtimeLoader.modelPtr
        if (!runtimeLoader.isLoaded() || ptr <= 0L) {
            Log.w(TAG, "modelPtr=$ptr — review_required (local_runtime_not_ready)")
            return@withContext makeReviewRequired(qcPoints, "local_runtime_not_ready")
        }

        val schemaExample = JSONObject().apply {
            put("overall_result", "pass | fail | review_required")
            put("confidence", 0.9)
            put("model_name", modelName)
            put("summary", "")
            put("items", JSONArray())
            put("fallback", JSONObject().apply {
                put("used", false)
                put("reason", JSONObject.NULL)
            })
        }.toString(2)

        val prompt      = QcPromptBuilder.build(standardPhotos, capturedPhoto, qcPoints, schemaExample)
        val expectedIds = qcPoints.map { it.qcPointId }
        val imgJson     = buildImageInputJson(standardPhotos, capturedPhoto)

        Log.i(TAG, "nativeRunInference start: ptr=$ptr qcPoints=${qcPoints.size}")

        return@withContext try {
            val rawJson = NativeMnnQwenBridge.nativeRunInference(
                ptr,
                imgJson,
                prompt,
                INFERENCE_PARAMS,
            )
            lastRawOutputLength = rawJson.length
            Log.i(TAG, "nativeRunInference complete: raw_output_length=${rawJson.length}")

            if (rawJson.isBlank()) {
                Log.w(TAG, "nativeRunInference blank output — review_required (empty_mnn_output)")
                makeReviewRequired(qcPoints, "empty_mnn_output")
            } else {
                QcResultParser.parse(rawJson, expectedIds, engineName)
            }
        } catch (e: Exception) {
            lastRawOutputLength = -1
            Log.e(TAG, "nativeRunInference threw: ${e.message} — review_required (native_exception)")
            makeReviewRequired(qcPoints, "native_exception: ${e.message}")
        }
    }

    private fun buildImageInputJson(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
    ): String = JSONObject().apply {
        put("standard_photos", JSONArray(standardPhotos.map { it.localPath }))
        put("captured_photo", capturedPhoto.localPath)
    }.toString()

    private fun makeReviewRequired(qcPoints: List<QcPointInput>, reason: String) =
        QwenInspectionOutput(
            overallResult = "review_required",
            engine        = engineName,
            modelName     = modelName,
            confidence    = 0.0f,
            items = qcPoints.map { p ->
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
            summary  = "Local MNN: $reason",
        )
}
