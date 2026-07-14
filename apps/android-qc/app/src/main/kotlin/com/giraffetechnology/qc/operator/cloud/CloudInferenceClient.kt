package com.giraffetechnology.qc.operator.cloud

import android.net.Network
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import java.time.Instant
import java.util.Base64

interface OperatorCloudClient {
    suspend fun submit(jobId: String, manifest: JSONObject, crops: List<EncodedCrop>): CloudSubmitOutcome
    suspend fun reconcile(jobId: String, manifest: JSONObject, crops: List<EncodedCrop>): CloudSubmitOutcome
    suspend fun health(): Boolean
    suspend fun probe(network: Network? = null): NetworkProbeResult?
}

class CloudInferenceClient(
    private val baseUrl: String,
    private val bearerToken: String,
    private val keyId: String,
    private val signer: CloudDeviceSigner,
    private val timeoutMs: Int = 9_000,
) : OperatorCloudClient {
    override suspend fun submit(jobId: String, manifest: JSONObject, crops: List<EncodedCrop>): CloudSubmitOutcome =
        withContext(Dispatchers.IO) {
            require(crops.isNotEmpty())
            require(bearerToken.isNotBlank() && keyId.isNotBlank()) { "cloud_device_not_provisioned" }
            require(crops.all { it.bytes.size <= CompressionProfile.HARD_MAX_CROP_BYTES })
            val canonical = canonicalJson(manifest)
            val digestInput = buildString {
                append(canonical).append('\n')
                crops.forEach { append(it.sha256).append('\n') }
            }.toByteArray()
            val contentDigest = digestInput.sha256Hex()
            val timestamp = Instant.now().toString()
            val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
                .let { Base64.getUrlEncoder().withoutPadding().encodeToString(it) }
            val path = JOBS_PATH
            val signatureInput = "QC-CLOUD-INFERENCE-V1\nPOST\n$path\n$timestamp\n$nonce\n$contentDigest\n$jobId\n"
            val boundary = "giraffe-${SecureRandom().nextLong().toString(16)}"
            val body = multipart(boundary, canonical, crops)
            val conn = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = timeoutMs.coerceAtMost(3_000)
                readTimeout = timeoutMs
                doOutput = true
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setRequestProperty("Accept", "application/json")
                setRequestProperty("Authorization", "Bearer $bearerToken")
                setRequestProperty("Idempotency-Key", jobId)
                setRequestProperty("X-QC-Key-Id", keyId)
                setRequestProperty("X-QC-Timestamp", timestamp)
                setRequestProperty("X-QC-Nonce", nonce)
                setRequestProperty("X-QC-Content-SHA256", contentDigest)
                setRequestProperty("X-QC-Signature", signer.sign(signatureInput.toByteArray()))
            }
            try {
                conn.outputStream.use { it.write(body) }
                val code = conn.responseCode
                val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() }.orEmpty()
                if (code !in 200..299) return@withContext parseError(code, text)
                parseRecognition(jobId, JSONObject(text), manifest, crops)
            } catch (e: Exception) {
                CloudSubmitOutcome.Retryable(e.message ?: "cloud_transport_error")
            } finally { conn.disconnect() }
        }

    override suspend fun reconcile(
        jobId: String,
        manifest: JSONObject,
        crops: List<EncodedCrop>,
    ): CloudSubmitOutcome = withContext(Dispatchers.IO) {
        if (bearerToken.isBlank()) return@withContext CloudSubmitOutcome.Rejected("cloud_device_not_provisioned")
        val path = "$JOBS_PATH/$jobId"
        val conn = (URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 2_000
            readTimeout = 3_000
            setRequestProperty("Authorization", "Bearer $bearerToken")
            setRequestProperty("Accept", "application/json")
        }
        try {
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code == 404) return@withContext CloudSubmitOutcome.Retryable("job_not_found")
            if (code !in 200..299) return@withContext parseError(code, text)
            val json = JSONObject(text)
            when (json.optString("status")) {
                "completed" -> parseRecognition(jobId, json, manifest, crops)
                "processing" -> CloudSubmitOutcome.Retryable("job_processing")
                "failed" -> CloudSubmitOutcome.Rejected(
                    json.optJSONObject("error")?.optString("code") ?: "cloud_job_failed"
                )
                else -> CloudSubmitOutcome.Retryable("unknown_job_status")
            }
        } catch (e: Exception) {
            CloudSubmitOutcome.Retryable(e.message ?: "cloud_reconcile_error")
        } finally {
            conn.disconnect()
        }
    }

    override suspend fun health(): Boolean = withContext(Dispatchers.IO) {
        if (bearerToken.isBlank()) return@withContext false
        val conn = (URL(baseUrl.trimEnd('/') + HEALTH_PATH).openConnection() as HttpURLConnection).apply {
            connectTimeout = 2_000; readTimeout = 2_000
            setRequestProperty("Authorization", "Bearer $bearerToken")
            setRequestProperty("Accept", "application/json")
        }
        try {
            conn.responseCode == 200 && JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                .optBoolean("accepting_jobs", false)
        } catch (_: Exception) { false } finally { conn.disconnect() }
    }

    override suspend fun probe(network: Network?): NetworkProbeResult? = withContext(Dispatchers.IO) {
        if (bearerToken.isBlank() || keyId.isBlank()) return@withContext null
        val body = ByteArray(32 * 1024).also { SecureRandom().nextBytes(it) }
        val digest = body.sha256Hex()
        val timestamp = Instant.now().toString()
        val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }
            .let { Base64.getUrlEncoder().withoutPadding().encodeToString(it) }
        val signatureInput = "QC-CLOUD-INFERENCE-V1\nPOST\n$PROBE_PATH\n$timestamp\n$nonce\n$digest\n\n"
        val url = URL(baseUrl.trimEnd('/') + PROBE_PATH)
        val conn = ((network?.openConnection(url) ?: url.openConnection()) as HttpURLConnection).apply {
            requestMethod = "POST"; connectTimeout = 2_000; readTimeout = 3_000; doOutput = true
            setRequestProperty("Content-Type", "application/octet-stream")
            setRequestProperty("Authorization", "Bearer $bearerToken")
            setRequestProperty("X-QC-Key-Id", keyId); setRequestProperty("X-QC-Timestamp", timestamp)
            setRequestProperty("X-QC-Nonce", nonce); setRequestProperty("X-QC-Content-SHA256", digest)
            setRequestProperty("X-QC-Signature", signer.sign(signatureInput.toByteArray()))
        }
        val started = System.nanoTime()
        try {
            conn.outputStream.use { it.write(body) }
            if (conn.responseCode !in 200..299) return@withContext null
            conn.inputStream.bufferedReader().use { it.readText() }
            val elapsedMs = ((System.nanoTime() - started) / 1_000_000).coerceAtLeast(1)
            NetworkProbeResult(body.size * 8.0 / elapsedMs / 1000.0, elapsedMs, 0.0)
        } catch (_: Exception) { null } finally { conn.disconnect() }
    }

    private fun parseRecognition(
        jobId: String,
        json: JSONObject,
        manifest: JSONObject,
        crops: List<EncodedCrop>,
    ): CloudSubmitOutcome {
        if (json.optString("status") != "completed") return CloudSubmitOutcome.Retryable("cloud_not_completed")
        val array = json.optJSONArray("point_results") ?: return CloudSubmitOutcome.Rejected("missing_point_results")
        val points = (0 until array.length()).map { i ->
            val point = array.getJSONObject(i)
            val result = point.getString("result")
            require(result in setOf("pass", "fail", "uncertain")) { "unknown_point_result" }
            CloudPointResult(
                pointCode = point.getString("point_code"), cropId = point.getString("crop_id"),
                result = result, confidence = point.getDouble("confidence").toFloat(),
                evidence = point.optString("evidence"),
                cvStatus = point.optString("cv_status", "not_configured"),
                cvAnalysisJson = point.optJSONObject("cv_analysis")?.toString(),
            )
        }
        val expected = crops.map { it.pointCode }.toSet()
        if (points.map { it.pointCode }.toSet() != expected || points.size != expected.size) {
            return CloudSubmitOutcome.Rejected("point_result_mismatch")
        }
        val overall = json.optString("recognition_overall_result")
        if (overall !in setOf("pass", "fail", "review_required")) return CloudSubmitOutcome.Rejected("unknown_overall_result")
        val model = json.optJSONObject("model") ?: JSONObject()
        val clientTiming = manifest.getJSONObject("client_timing")
        return CloudSubmitOutcome.Completed(
            CloudRecognition(
                jobId = jobId, overallResult = overall, pointResults = points,
                providerAdapter = model.optString("provider_adapter", "configured-cloud-vlm"),
                modelFamily = model.optString("family", "configured-cloud-vlm"),
                timing = CloudTiming(
                    captureConfirmedAt = clientTiming.getString("capture_confirmed_at"),
                    cvStartedAt = clientTiming.getString("cv_started_at"),
                    cvCompletedAt = clientTiming.getString("cv_completed_at"),
                    responseReceivedAt = Instant.now().toString(),
                ),
            )
        )
    }

    private fun parseError(code: Int, body: String): CloudSubmitOutcome {
        val error = runCatching { JSONObject(body).getJSONObject("error") }.getOrNull()
        val errorCode = error?.optString("code")?.takeIf { it.isNotBlank() } ?: "http_$code"
        return if (error?.optBoolean("retryable", code >= 500) == true || code >= 500 || code == 408 || code == 429) {
            CloudSubmitOutcome.Retryable(errorCode)
        } else CloudSubmitOutcome.Rejected(errorCode)
    }

    private fun multipart(boundary: String, manifest: String, crops: List<EncodedCrop>): ByteArray =
        ByteArrayOutputStream().use { out ->
            fun line(value: String) = out.write((value + "\r\n").toByteArray())
            line("--$boundary")
            line("Content-Disposition: form-data; name=\"manifest\"")
            line("Content-Type: application/json; charset=utf-8")
            line("")
            line(manifest)
            crops.forEach { crop ->
                line("--$boundary")
                line("Content-Disposition: form-data; name=\"${crop.cropId}.jpg\"; filename=\"${crop.cropId}.jpg\"")
                line("Content-Type: image/jpeg")
                line("")
                out.write(crop.bytes); line("")
            }
            line("--$boundary--")
            out.toByteArray()
        }

    companion object {
        const val JOBS_PATH = "/api/v2/operator-inference/jobs"
        const val HEALTH_PATH = "/api/v2/operator-inference/health"
        const val PROBE_PATH = "/api/v2/operator-inference/network-probe"

        internal fun canonicalJson(value: Any?): String = when (value) {
            null, JSONObject.NULL -> "null"
            is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") {
                JSONObject.quote(it) + ":" + canonicalJson(value.get(it))
            }
            is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonicalJson(value.get(it)) }
            is String -> JSONObject.quote(value)
            is Number, is Boolean -> value.toString()
            else -> error("unsupported_json_type")
        }
    }
}
