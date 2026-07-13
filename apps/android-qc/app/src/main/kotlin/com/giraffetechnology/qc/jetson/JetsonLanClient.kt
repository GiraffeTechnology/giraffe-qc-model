package com.giraffetechnology.qc.jetson

import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

/**
 * Low-level LAN HTTP client for the Xavier NX runner, per
 * `docs/api-contracts/jetson-runner-api.md` §1. Uses `HttpURLConnection`
 * (this codebase's established convention -- no OkHttp, see
 * `HttpSubmissionClient`/`ApiSkuRepository`), with an injectable transport
 * seam for JVM unit tests (mirrors `ApiSkuRepository`'s `HttpTransport`
 * pattern, extended here to also support POST since inference/pairing calls
 * need a request body).
 *
 * This client never throws to signal "unreachable" -- every method returns
 * null/a typed failure on any transport error, matching the fail-closed
 * philosophy already used by `MnnQwenInspector`/`ApiSkuRepository`: callers
 * (`JetsonRuntimeMonitor`, `JetsonQwenInspector`) decide what "unreachable"
 * means for their own state, this class just reports it honestly.
 */
internal data class JetsonHttpResponse(val code: Int, val body: String?)

internal interface JetsonHttpTransport {
    fun get(url: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse
    fun post(url: String, body: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse
}

internal class RealJetsonHttpTransport : JetsonHttpTransport {
    override fun get(url: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse =
        request(url, "GET", null, connectTimeoutMs, readTimeoutMs)

    override fun post(url: String, body: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse =
        request(url, "POST", body, connectTimeoutMs, readTimeoutMs)

    private fun request(url: String, method: String, body: String?, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse {
        val conn = URL(url).openConnection() as HttpURLConnection
        return try {
            conn.requestMethod = method
            conn.connectTimeout = connectTimeoutMs
            conn.readTimeout = readTimeoutMs
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.let { BufferedReader(InputStreamReader(it, Charsets.UTF_8)).readText() }
            JetsonHttpResponse(code, text)
        } catch (e: Exception) {
            JetsonHttpResponse(-1, null)
        } finally {
            conn.disconnect()
        }
    }
}

class JetsonLanClient internal constructor(
    private val transport: JetsonHttpTransport,
    private val connectTimeoutMs: Int,
    private val readTimeoutMs: Int,
) {
    constructor(connectTimeoutMs: Int = 3000, readTimeoutMs: Int = 5000) :
        this(RealJetsonHttpTransport(), connectTimeoutMs, readTimeoutMs)

    fun health(baseUrl: String): JetsonHealthSnapshot? {
        val resp = transport.get("$baseUrl/health", connectTimeoutMs, readTimeoutMs)
        if (resp.code != 200 || resp.body == null) return null
        return runCatching {
            val json = JSONObject(resp.body)
            JetsonHealthSnapshot(
                serviceUp = json.optBoolean("service_up", false),
                modelLoaded = json.optBoolean("model_loaded", false),
                temperatureC = if (json.has("temperature_c") && !json.isNull("temperature_c")) json.optDouble("temperature_c") else null,
                throttling = if (json.has("throttling") && !json.isNull("throttling")) json.optBoolean("throttling") else null,
                diskFreePercent = if (json.has("disk_free_percent") && !json.isNull("disk_free_percent")) json.optDouble("disk_free_percent") else null,
                lastInferenceLatencyMs = if (json.has("last_inference_latency_ms") && !json.isNull("last_inference_latency_ms")) json.optInt("last_inference_latency_ms") else null,
                readinessState = JetsonReadinessState.fromWire(json.optString("readiness_state", null)),
                jetsonDeviceId = json.optString("jetson_device_id", ""),
                agentVersion = json.optString("agent_version", ""),
                adapterName = if (json.has("adapter_name")) json.optString("adapter_name") else null,
                modelName = if (json.has("model_name")) json.optString("model_name") else null,
                polledAtEpochMs = System.currentTimeMillis(),
                isMock = json.optBoolean("mock", false),
            )
        }.getOrNull()
    }

    data class PairingHandshake(
        val jetsonDeviceId: String,
        val jetsonPubkey: String,
        val pairKey: String,
        val pairingPath: String,
    )

    sealed class PairingOutcome {
        data class Success(val handshake: PairingHandshake) : PairingOutcome()
        data class Rejected(val reason: String) : PairingOutcome()
        object Unreachable : PairingOutcome()
    }

    fun pairUsb(baseUrl: String, padDeviceId: String, padPubkey: String): PairingOutcome {
        val body = JSONObject().put("pad_device_id", padDeviceId).put("pad_pubkey", padPubkey)
        return pair("$baseUrl/pair/usb", body)
    }

    fun pairWifi(baseUrl: String, padDeviceId: String, padPubkey: String, confirmedFingerprint: String): PairingOutcome {
        val body = JSONObject()
            .put("pad_device_id", padDeviceId)
            .put("pad_pubkey", padPubkey)
            .put("confirmed_fingerprint", confirmedFingerprint)
        return pair("$baseUrl/pair/wifi", body)
    }

    private fun pair(url: String, body: JSONObject): PairingOutcome {
        val resp = transport.post(url, body.toString(), connectTimeoutMs, readTimeoutMs)
        if (resp.code == -1) return PairingOutcome.Unreachable
        if (resp.body == null) return PairingOutcome.Rejected("empty_response")
        return runCatching {
            val json = JSONObject(resp.body)
            if (resp.code == 200) {
                PairingOutcome.Success(
                    PairingHandshake(
                        jetsonDeviceId = json.getString("jetson_device_id"),
                        jetsonPubkey = json.getString("jetson_pubkey"),
                        pairKey = json.getString("pair_key"),
                        pairingPath = json.getString("pairing_path"),
                    ),
                )
            } else {
                PairingOutcome.Rejected(json.optString("detail", "rejected"))
            }
        }.getOrElse { PairingOutcome.Rejected("malformed_response") }
    }

    sealed class InferOutcome {
        data class Success(val response: JetsonInferenceResponse) : InferOutcome()
        data class Rejected(val reason: String) : InferOutcome()
        object Unreachable : InferOutcome()
    }

    fun infer(baseUrl: String, padDeviceId: String, pairKey: String, request: JetsonInferenceRequest): InferOutcome {
        val requestJson = request.toJson()
        val signature = signJetsonRequest(pairKey, requestJson)
        val envelope = JSONObject()
            .put("pad_device_id", padDeviceId)
            .put("signature", signature)
            .put("request", requestJson)
        val resp = transport.post("$baseUrl/infer", envelope.toString(), connectTimeoutMs, readTimeoutMs)
        if (resp.code == -1) return InferOutcome.Unreachable
        if (resp.body == null) return InferOutcome.Rejected("empty_response")
        return runCatching {
            val json = JSONObject(resp.body)
            if (resp.code == 200) {
                InferOutcome.Success(JetsonInferenceResponse.fromJson(json))
            } else {
                InferOutcome.Rejected(json.optString("detail", "rejected"))
            }
        }.getOrElse { InferOutcome.Rejected("malformed_response") }
    }
}
