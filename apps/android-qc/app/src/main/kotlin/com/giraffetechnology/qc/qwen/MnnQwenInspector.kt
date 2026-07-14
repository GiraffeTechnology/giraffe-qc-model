package com.giraffetechnology.qc.qwen

import android.content.Context
import android.util.Log
import com.giraffetechnology.qc.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject

/**
 * On-device QWEN inspector backed by the MNN inference engine (§4.3.3).
 *
 * Model: Qwen3-VL-2B-Instruct-MNN (INT4), loaded by [MnnRuntimeLoader].
 *
 * ## Real inference path
 * [inspect] assembles the standard photos + captured photo + QC points into a
 * request, runs one native visual+LLM pass via [MnnRuntimeLoader.runInference],
 * and parses the raw output with [QcResultParser] — the SAME no-guess rules as
 * the server parser: hallucinated QC-point IDs are rejected, missing points
 * become review_required, and the overall verdict is recomputed deterministically
 * rather than trusted from the model's self-report.
 *
 * ## Fail-closed behavior
 * - If the runtime is not loaded, throws UnsupportedOperationException — the
 *   router/coordinator treat this as "not provisioned" → review_required.
 * - A native error, crash, timeout, or OOM surfaces as an exception; the caller
 *   fails closed to review_required. Inference runs off the main thread, so a
 *   hung native call cannot wedge the UI. NOTE: a truly hung JNI call cannot be
 *   force-killed from Kotlin — [withTimeout] abandons the wait and returns an
 *   error, but the native worker may keep running until it completes/crashes.
 */
class MnnQwenInspector(
    private val context: Context,
    private val runtimeLoader: MnnRuntimeLoader,
    override val modelName: String = "Qwen3-VL-2B-Instruct-MNN",
    private val timeoutMs: Long = BuildConfig.LEGACY_MNN_TIMEOUT_SECONDS * 1000L,
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
            put("items", JSONArray())
            put("fallback", JSONObject().apply {
                put("used", false); put("reason", JSONObject.NULL)
            })
        }.toString(2)

        val prompt = QcPromptBuilder.build(
            standardPhotos, capturedPhoto, qcPoints, schemaExample,
        )

        val requestJson = buildRequestJson(standardPhotos, capturedPhoto, prompt)

        // Run the native pass under a timeout so a hung/crashed call surfaces as
        // an inference error (→ review_required) instead of blocking forever.
        val rawJson = try {
            withTimeout(timeoutMs) {
                withContext(Dispatchers.IO) { runtimeLoader.runInference(requestJson) }
            }
        } catch (e: TimeoutCancellationException) {
            Log.w(TAG, "On-device inference timed out after ${timeoutMs}ms")
            throw IllegalStateException("on_device_inference_timeout", e)
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e // preserve structured concurrency cancellation
        } catch (e: Throwable) {
            // OutOfMemoryError, UnsatisfiedLinkError, native crash surfaced as
            // exception, etc. — never let it become a fake pass.
            Log.e(TAG, "On-device inference error: ${e.message}")
            throw IllegalStateException("on_device_inference_error", e)
        }

        // Deterministic recomputation is inside QcResultParser: it rebuilds the
        // per-point item list from the expected QC-point IDs and never lets the
        // model's self-reported overall verdict override that.
        QcResultParser.parse(rawJson, qcPoints.map { it.qcPointId }, engineName)
    }

    /**
     * Assembles the native request: the image references (standard + captured)
     * plus the prompt text. The native bridge decodes the referenced image files
     * for the visual encoder. Only local file paths are passed — no network URLs,
     * no cloud endpoints (padLocal is local-only).
     */
    private fun buildRequestJson(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        prompt: String,
    ): String {
        val images = JSONArray()
        standardPhotos.forEach { p ->
            images.put(JSONObject().apply {
                put("role", "standard")
                put("photo_id", p.photoId)
                put("path", p.localPath)
                p.angle?.let { put("angle", it) }
            })
        }
        images.put(JSONObject().apply {
            put("role", "captured")
            put("photo_id", capturedPhoto.photoId)
            put("path", capturedPhoto.localPath)
        })
        return JSONObject().apply {
            put("model_name", modelName)
            put("images", images)
            put("prompt", prompt)
        }.toString()
    }
}
