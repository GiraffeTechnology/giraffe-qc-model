package com.giraffetechnology.qc.submit

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Posts cloud recognition results to the Server S4 recomputation endpoint using
 * [HttpURLConnection] (no OkHttp dependency, matching the SKU client).
 *
 * This uploads **result metadata only** — it is not a QC-inference call and
 * carries no cloud model traffic, so it does not violate the Pad's local-only
 * inference rule. The Server dedupes idempotently on `client_job_id`; on any
 * non-2xx or transport error the whole batch is reported [SubmitResult.Failed]
 * and nothing is marked uploaded, so it retries cleanly next window.
 */
class HttpSubmissionClient(
    private val baseUrl: String,
    private val path: String = DEFAULT_PATH,
    private val timeoutMs: Int = 15_000,
) : SubmissionClient {

    override suspend fun submit(batch: List<ResultSubmission>): SubmitResult =
        withContext(Dispatchers.IO) {
            if (batch.isEmpty()) return@withContext SubmitResult.Accepted(emptyList())
            val accepted = mutableListOf<String>()
            for (submission in batch) {
                val url = URL(baseUrl.trimEnd('/') + path)
                val conn = (url.openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"; connectTimeout = timeoutMs; readTimeout = timeoutMs; doOutput = true
                    setRequestProperty("Content-Type", "application/json"); setRequestProperty("Accept", "application/json")
                }
                try {
                    conn.outputStream.use { it.write(encodeS4Body(submission).toByteArray(Charsets.UTF_8)) }
                    val code = conn.responseCode
                    if (code !in 200..299) {
                        val err = runCatching { conn.errorStream?.bufferedReader()?.readText() }.getOrNull()
                        Log.w(TAG, "S4 result upload failed: HTTP $code ${err.orEmpty()}")
                        return@withContext SubmitResult.Failed("HTTP $code")
                    }
                    accepted += submission.clientJobId
                } catch (e: Exception) {
                    Log.w(TAG, "S4 result upload error: ${e.message}")
                    return@withContext SubmitResult.Failed(e.message ?: "network error")
                } finally { conn.disconnect() }
            }
            SubmitResult.Accepted(accepted)
        }

    companion object {
        private const val TAG = "HttpSubmissionClient"
        const val DEFAULT_PATH = "/api/qc/results/submissions"

        internal fun encodeS4Body(s: ResultSubmission): String {
            val checkpoints = runCatching { JSONArray(s.pointResultsJson ?: "[]") }.getOrDefault(JSONArray())
            val mapped = JSONArray()
            for (i in 0 until checkpoints.length()) {
                val point = checkpoints.getJSONObject(i)
                mapped.put(JSONObject().put("checkpoint_id", point.getString("point_code"))
                    .put("result", point.getString("result")))
            }
            val overall = when (s.modelResult) {
                "ACCEPTED" -> "pass"; "NOT_ACCEPTED" -> "fail"; else -> "review_required"
            }
            return JSONObject().put("tenant_id", s.tenantId)
                .put("job_ref", s.cloudJobId ?: s.clientJobId)
                .put("standard_revision_id", s.standardRevisionId ?: "")
                .put("bundle_version", s.bundleVersion ?: "")
                .put("pad_overall_result", overall).put("checkpoints", mapped)
                .put("expected_bundle_version", s.bundleVersion ?: JSONObject.NULL)
                .put("cloud_recognition", checkpoints)
                .put("client_timing", runCatching { JSONObject(s.timingJson ?: "{}") }.getOrDefault(JSONObject()))
                .toString()
        }

        internal fun encodeBody(batch: List<ResultSubmission>): String {
            val jobs = JSONArray()
            batch.forEach { s ->
                jobs.put(
                    JSONObject().apply {
                        put("client_job_id", s.clientJobId)
                        put("tenant_id", s.tenantId)
                        put("sku_id", s.skuId)
                        put("item_number", s.itemNumber)
                        put("standard_revision_id", s.standardRevisionId ?: JSONObject.NULL)
                        put("bundle_version", s.bundleVersion ?: JSONObject.NULL)
                        put("model_result", s.modelResult)
                        put("human_decision", s.humanDecision.wire)
                        put("reason", s.reason)
                        put("model_name", s.modelName)
                        put("captured_image_path", s.capturedImagePath ?: JSONObject.NULL)
                        put("created_at", s.createdAtEpochMs)
                    }
                )
            }
            return JSONObject().put("jobs", jobs).toString()
        }

        /**
         * Read the accepted client job ids from the response. If the Server does
         * not echo them but returned 2xx, every submitted id is treated as
         * accepted (the endpoint is idempotent by client_job_id).
         */
        internal fun parseAcceptedIds(body: String, batch: List<ResultSubmission>): List<String> {
            val submitted = batch.map { it.clientJobId }
            if (body.isBlank()) return submitted
            return runCatching {
                val obj = JSONObject(body)
                val arr = obj.optJSONArray("accepted_job_ids")
                    ?: obj.optJSONArray("accepted")
                    ?: return submitted
                (0 until arr.length()).map { arr.getString(it) }
            }.getOrDefault(submitted)
        }
    }
}
