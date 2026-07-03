package com.giraffetechnology.qc.sync

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Sync-window network client (Task 03). Used ONLY during a sync window (shift
 * change / office Wi-Fi); production inspection never calls it.
 *
 * The interface is the seam tested with a fake in unit tests. The HTTP
 * implementation ([HttpBundleSyncClient]) talks to the server's Task 03 endpoints
 * and is exercised end-to-end on-device / against a running server (PENDING here).
 */
interface BundleSyncClient {
    /** Latest bundle version for the scope, or null if the server has none. */
    suspend fun latestBundleVersion(tenantId: String, lineScope: String): Int?

    /** Download the latest bundle archive bytes, or null if none. */
    suspend fun downloadLatest(tenantId: String, lineScope: String): ByteArray?

    /** Upload a batch of outbox jobs; returns the server's per-job outcome. */
    suspend fun uploadBatch(tenantId: String, jobs: List<OutboxJob>): List<UploadJobOutcome>
}

class HttpBundleSyncClient(
    private val baseUrl: String,
    private val connectTimeoutMs: Int = 15_000,
    private val readTimeoutMs: Int = 60_000,
) : BundleSyncClient {

    override suspend fun latestBundleVersion(tenantId: String, lineScope: String): Int? {
        val url = URL("$baseUrl/api/v1/qc/bundles/latest?tenant_id=${enc(tenantId)}&line_scope=${enc(lineScope)}")
        val (code, body) = httpGet(url)
        if (code == 404) return null
        if (code !in 200..299) error("latest check failed: HTTP $code")
        return JSONObject(body).optInt("bundle_version").takeIf { it > 0 }
    }

    override suspend fun downloadLatest(tenantId: String, lineScope: String): ByteArray? {
        val metaUrl = URL("$baseUrl/api/v1/qc/bundles/latest?tenant_id=${enc(tenantId)}&line_scope=${enc(lineScope)}")
        val (code, body) = httpGet(metaUrl)
        if (code == 404) return null
        if (code !in 200..299) error("latest check failed: HTTP $code")
        val downloadPath = JSONObject(body).getString("download_url")
        val dlUrl = URL("$baseUrl$downloadPath?tenant_id=${enc(tenantId)}")
        return httpGetBytes(dlUrl)
    }

    override suspend fun uploadBatch(tenantId: String, jobs: List<OutboxJob>): List<UploadJobOutcome> {
        val payload = JSONObject().apply {
            put("tenant_id", tenantId)
            put("jobs", JSONArray().apply { jobs.forEach { put(jobJson(it)) } })
        }
        val url = URL("$baseUrl/api/v1/qc/inspection-jobs/batch")
        val (code, body) = httpPostJson(url, payload.toString())
        if (code !in 200..299) error("batch upload failed: HTTP $code")
        val results = JSONObject(body).optJSONArray("results") ?: JSONArray()
        val out = ArrayList<UploadJobOutcome>(results.length())
        for (i in 0 until results.length()) {
            val r = results.getJSONObject(i)
            val reason = if (r.isNull("reason")) null else r.optString("reason").ifEmpty { null }
            out.add(UploadJobOutcome(r.getString("job_uuid"), r.getString("status"), reason))
        }
        return out
    }

    private fun jobJson(job: OutboxJob): JSONObject = JSONObject().apply {
        put("job_uuid", job.jobUuid)
        put("sku_id", job.skuId)
        put("active_standard_revision_id", job.activeStandardRevisionId)
        put("overall_result", job.overallResult)
        job.createdBy?.let { put("created_by", it) }
        job.jobRef?.let { put("job_ref", it) }
        job.notes?.let { put("notes", it) }
        job.startedAt?.let { put("started_at", it) }
        job.completedAt?.let { put("completed_at", it) }
        put("checkpoint_results", JSONArray().apply {
            job.checkpoints.forEach { cp ->
                put(JSONObject().apply {
                    put("detection_point_id", cp.detectionPointId)
                    put("result", cp.result)
                    put("confidence", cp.confidence.toDouble())
                    cp.observedValue?.let { put("observed_value", it) }
                    cp.notes?.let { put("notes", it) }
                })
            }
        })
        put("media", JSONArray().apply {
            job.media.forEach { m ->
                put(JSONObject().apply {
                    m.localPath?.let { put("local_path", it) }
                    m.sha256?.let { put("sha256", it) }
                    m.angle?.let { put("angle", it) }
                    m.viewType?.let { put("view_type", it) }
                })
            }
        })
    }

    private fun enc(s: String) = java.net.URLEncoder.encode(s, "UTF-8")

    private fun httpGet(url: URL): Pair<Int, String> {
        val conn = open(url, "GET")
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            code to (stream?.bufferedReader()?.use { it.readText() } ?: "")
        } finally { conn.disconnect() }
    }

    private fun httpGetBytes(url: URL): ByteArray {
        val conn = open(url, "GET")
        return try {
            if (conn.responseCode !in 200..299) error("download failed: HTTP ${conn.responseCode}")
            conn.inputStream.use { it.readBytes() }
        } finally { conn.disconnect() }
    }

    private fun httpPostJson(url: URL, json: String): Pair<Int, String> {
        val conn = open(url, "POST")
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        return try {
            conn.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            code to (stream?.bufferedReader()?.use { it.readText() } ?: "")
        } finally { conn.disconnect() }
    }

    private fun open(url: URL, method: String): HttpURLConnection =
        (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = connectTimeoutMs
            readTimeout = readTimeoutMs
        }
}
