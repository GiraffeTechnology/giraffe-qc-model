package com.giraffetechnology.qc.multimodal

import android.util.Log
import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.FallbackInfo
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.InspectionItemResult
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

/**
 * Calls POST /api/v1/qc/inspect on the backend server.
 *
 * Used when PAD_ALLOW_BACKEND_PROXY=true. Images are sent as local file paths;
 * the server must mount the same filesystem or a configured network share.
 *
 * Fail-closed: any network error, non-2xx status, timeout, or parse failure
 * returns review_required. This inspector never calls cloud providers directly.
 *
 * Sends X-QC-Contract-Version header on every request for server-side version checks.
 */
class BackendProxyInspector(
    private val baseUrl: String,
    private val timeoutMs: Int = 30_000,
) : MultimodalInspector {

    override val inspectorName: String = "backend_proxy"
    override val modelName: String = "server_delegated"

    companion object {
        private const val TAG = "BackendProxyInspector"
        private const val ENDPOINT = "/api/v1/qc/inspect"
    }

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = withContext(Dispatchers.IO) {
        if (baseUrl.isBlank()) {
            Log.w(TAG, "backendBaseUrl is blank — review_required (backend_url_not_configured)")
            return@withContext makeReviewRequired(qcPoints, "backend_url_not_configured")
        }

        val body = buildRequestJson(standardPhotos, capturedPhoto, qcPoints, context)
        return@withContext try {
            val conn = (URL("$baseUrl$ENDPOINT").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("X-QC-Contract-Version", SharedQcContract.QC_CONTRACT_VERSION)
                doOutput = true
                OutputStreamWriter(outputStream, Charsets.UTF_8).use { it.write(body) }
            }
            val code = conn.responseCode
            if (code !in 200..299) {
                Log.w(TAG, "Backend HTTP $code — review_required")
                return@withContext makeReviewRequired(qcPoints, "backend_http_error_$code")
            }
            val responseText = conn.inputStream.bufferedReader(Charsets.UTF_8).readText()
            parseServerResponse(responseText, qcPoints)
        } catch (e: Exception) {
            Log.w(TAG, "Backend call failed: ${e.message} — review_required")
            makeReviewRequired(qcPoints, "backend_network_error:${e.javaClass.simpleName}")
        }
    }

    private fun buildRequestJson(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): String = JSONObject().apply {
        put("contract_version", SharedQcContract.QC_CONTRACT_VERSION)
        put("tenant_id", context.tenantId)
        put("sku_id", context.skuId)
        put("standard_id", context.standardId)
        put("inspection_id", context.inspectionId)
        put("standard_image_paths", JSONArray(standardPhotos.map { it.localPath }))
        put("captured_image_path", capturedPhoto.localPath)
        put("qc_points", JSONArray(qcPoints.map { p ->
            JSONObject().apply {
                put("qc_point_id", p.qcPointId)
                put("qc_point_code", p.qcPointCode)
                put("name", p.name)
                put("description", p.description)
            }
        }))
    }.toString()

    private fun parseServerResponse(
        json: String,
        qcPoints: List<QcPointInput>,
    ): QwenInspectionOutput {
        if (json.isBlank()) return makeReviewRequired(qcPoints, "backend_empty_response")
        return try {
            val obj = JSONObject(json)
            val overall = SharedQcContract.normalizeResult(obj.optString("overall_result"))
            val confidence = obj.optDouble("confidence", 0.0).coerceIn(0.0, 1.0).toFloat()
            val engine = obj.optString("engine", "server")
            val model = obj.optString("model_name", modelName)
            val summary = obj.optString("summary", "")

            val expectedIds = qcPoints.associateBy { it.qcPointId }
            val parsedItems = mutableMapOf<String, InspectionItemResult>()
            val itemsArr = obj.optJSONArray("items")
            if (itemsArr != null) {
                for (i in 0 until itemsArr.length()) {
                    val item = itemsArr.getJSONObject(i)
                    val id = item.optString("qc_point_id", "")
                    if (id.isBlank() || id !in expectedIds) continue
                    parsedItems[id] = InspectionItemResult(
                        qcPointId   = id,
                        qcPointCode = item.optString("qc_point_code", id),
                        name        = item.optString("name", id),
                        result      = SharedQcContract.normalizeResult(item.optString("result")),
                        confidence  = item.optDouble("confidence", 0.0).coerceIn(0.0, 1.0).toFloat(),
                        reason      = item.optString("reason", ""),
                    )
                }
            }
            val allItems = qcPoints.map { p ->
                parsedItems[p.qcPointId] ?: InspectionItemResult(
                    p.qcPointId, p.qcPointCode, p.name,
                    "review_required", 0.0f, "not_returned_by_server",
                )
            }
            val fbObj = obj.optJSONObject("fallback")
            val fallback = FallbackInfo(
                used   = fbObj?.optBoolean("used", false) ?: false,
                reason = if (fbObj != null && !fbObj.isNull("reason")) fbObj.optString("reason") else null,
            )
            QwenInspectionOutput(
                overallResult = overall,
                engine        = engine,
                modelName     = model,
                confidence    = confidence,
                items         = allItems,
                fallback      = fallback,
                summary       = summary,
            )
        } catch (_: Exception) {
            makeReviewRequired(qcPoints, "backend_parse_error")
        }
    }

    private fun makeReviewRequired(qcPoints: List<QcPointInput>, reason: String) =
        QwenInspectionOutput(
            overallResult = "review_required",
            engine        = inspectorName,
            modelName     = modelName,
            confidence    = 0.0f,
            items         = qcPoints.map { p ->
                InspectionItemResult(p.qcPointId, p.qcPointCode, p.name,
                    "review_required", 0.0f, reason)
            },
            fallback = FallbackInfo(used = false, reason = reason),
            summary  = "Backend proxy: $reason",
        )
}
