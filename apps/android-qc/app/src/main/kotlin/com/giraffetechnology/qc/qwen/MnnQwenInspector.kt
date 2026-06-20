package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * On-device QWEN inspector backed by MNN inference engine (§4.3.3).
 *
 * Hardware target: Snapdragon 8 Gen, 8 GB RAM.
 * Default model: Qwen3-VL-2B-Instruct-MNN (INT4).
 *
 * When MNN AAR is NOT present (CI / unit tests):
 * - loadModel() succeeds if model.mnn exists
 * - inspect() throws UnsupportedOperationException → router treats as "not provisioned"
 * Replace the stub in the inspect() body with the real JNI call once MNN AAR is integrated.
 */
class MnnQwenInspector(
    private val context: Context,
    private val runtimeLoader: MnnRuntimeLoader,
    override val modelName: String = "Qwen3-VL-2B-Instruct-MNN",
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
            Log.w(TAG, "Model not loaded — triggering fallback")
            throw UnsupportedOperationException("on_device_model_not_provisioned")
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

        // Production JNI call (replace this stub):
        // val rawJson = nativeRunInference(
        //     runtimeLoader.modelPtr,
        //     buildImageInputJson(standardPhotos, capturedPhoto),
        //     prompt,
        // )
        // return@withContext QcResultParser.parse(rawJson, expectedIds, engineName)

        // Scaffold: MNN AAR JNI not yet wired — triggers fallback in router
        throw UnsupportedOperationException(
            "MNN inference stub — replace with nativeRunInference() once AAR is integrated"
        )
    }
}
