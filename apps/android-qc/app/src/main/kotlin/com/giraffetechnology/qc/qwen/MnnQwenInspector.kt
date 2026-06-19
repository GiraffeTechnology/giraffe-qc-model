package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.random.Random

/**
 * On-device QWEN inspector backed by MNN inference engine (§4.3.3).
 *
 * Hardware target: Snapdragon 8 Gen, 8 GB RAM.
 * Default model: Qwen3-VL-4B-Instruct-MNN (INT4).
 *
 * Modes:
 *   STUB_MODE (MnnRuntimeLoader.stubMode = true): llm.mnn present but MNN AAR absent.
 *     inspect() simulates realistic inference latency and returns labeled stub results.
 *     Benchmark pipeline is fully exercised end-to-end; output is clearly marked STUB_MODE.
 *   PRODUCTION (stubMode = false): real JNI call via nativeRunInference().
 *     Requires MNN-android.aar dependency to be added to build.gradle.kts.
 *
 * Qwen3 thinking mode:
 *   Disabled via enable_thinking=false in buildInferenceParams() passed to nativeRunInference().
 *   QcResultParser.stripThinkingBlocks() provides a second layer of defence in case the
 *   MNN build ignores the flag (e.g. older runtime) or a future model re-enables thinking.
 *   Model-side: set "thinking_mode": false in the model's llm_config.json if available.
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
            Log.w(TAG, "Model not loaded — triggering fallback")
            throw UnsupportedOperationException("on_device_model_not_provisioned")
        }

        if (MnnRuntimeLoader.stubMode) {
            // Simulate realistic Qwen3-VL-4B inference time on Snapdragon 8 Gen (3–7 s/image).
            val simulatedMs = Random.nextLong(3_000L, 7_000L)
            delay(simulatedMs)
            Log.i(TAG, "STUB_MODE: simulated inference ${simulatedMs} ms")
            return@withContext QwenInspectionOutput(
                overallResult = "pass",
                engine        = "local_qwen_mnn_stub",
                modelName     = "$modelName (STUB_MODE)",
                confidence    = 0.94f,
                items         = qcPoints.map { p ->
                    InspectionItemResult(
                        qcPointId   = p.qcPointId,
                        qcPointCode = p.qcPointCode,
                        name        = p.name,
                        result      = "pass",
                        confidence  = 0.94f,
                        reason      = "STUB_MODE: simulated pass — integrate MNN-android.aar for real inference",
                    )
                },
                fallback = FallbackInfo(used = false),
                summary  = "STUB_MODE — MNN native libs absent. Simulated ${simulatedMs} ms. " +
                    "Wire MNN-android.aar to replace with real on-device numbers.",
            )
        }

        val schemaExample = org.json.JSONObject().apply {
            put("overall_result", "pass | fail | review_required")
            put("confidence", 0.9)
            put("model_name", modelName)
            put("summary", "")
            put("items", org.json.JSONArray())
            put("fallback", org.json.JSONObject().apply {
                put("used", false); put("reason", org.json.JSONObject.NULL)
            })
        }.toString(2)

        val prompt = QcPromptBuilder.build(
            standardPhotos, capturedPhoto, qcPoints, schemaExample
        )
        val expectedIds = qcPoints.map { it.qcPointId }

        // Production JNI call — uncomment once MNN-android.aar is in build.gradle.kts:
        // val rawJson = nativeRunInference(
        //     runtimeLoader.modelPtr,
        //     buildImageInputJson(standardPhotos, capturedPhoto),
        //     prompt,
        //     buildInferenceParams(),  // passes enable_thinking=false to suppress Qwen3 thinking mode
        // )
        // return@withContext QcResultParser.parse(rawJson, expectedIds, engineName)

        throw UnsupportedOperationException(
            "MNN inference JNI not wired — add MNN-android.aar to build.gradle.kts"
        )
    }

    /**
     * JSON parameters forwarded to nativeRunInference().
     * enable_thinking=false suppresses Qwen3's <think>…</think> reasoning prefix so the
     * model outputs structured JSON directly. QcResultParser.stripThinkingBlocks() is a
     * second safeguard in case the runtime ignores this flag.
     */
    private fun buildInferenceParams(): String =
        org.json.JSONObject().apply {
            put("enable_thinking", false)
            put("max_new_tokens", 512)
        }.toString()
}
