package com.giraffetechnology.qc.jetson

import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

/**
 * Best-effort relay of Jetson health to the qc-model Server so Account A's
 * WS3 admin fleet screen has fresh data (`docs/api-contracts/pad-jetson-health-state.md`
 * §3), reusing the already-implemented `POST /api/qc/jetson/runners/{id}/health`
 * (`src/api/jetson_router.py`, shipped in PR #51 -- no server change needed).
 *
 * Relay failures must **never** affect [PadJetsonState] or the fail-closed
 * gate -- those come from the Pad's direct LAN view of the Jetson only. A
 * failed/slow relay degrades admin *visibility*, never Operator *safety*, so
 * every failure here is swallowed after a best-effort attempt.
 *
 * **Known gap:** `POST /api/qc/jetson/bindings` (the pairing-completed
 * relay) is not implemented here -- it needs a `workstation_id` this
 * scaffold has no clean source for yet (Pad pairing flow doesn't currently
 * carry workstation context). Only the health relay, which needs no such
 * field, is implemented. Flagged as a follow-up, not silently dropped.
 */
class JetsonServerRelay(
    private val serverBaseUrl: String,
    private val connectTimeoutMs: Int = 3000,
    private val readTimeoutMs: Int = 3000,
) {
    fun relayHealth(tenantId: String, health: JetsonHealthSnapshot) {
        if (health.jetsonDeviceId.isBlank()) return
        val body = JSONObject()
            .put("tenant_id", tenantId)
            .put("jetson_device_id", health.jetsonDeviceId)
            .put("service_up", health.serviceUp)
            .put("model_loaded", health.modelLoaded)
            .put("temperature_c", health.temperatureC)
            .put("throttling", health.throttling)
            .put("disk_free_percent", health.diskFreePercent)
            .put("last_inference_latency_ms", health.lastInferenceLatencyMs)
            .put("readiness_state", health.readinessState.wireValue)
        runCatching {
            val conn = URL("$serverBaseUrl/api/qc/jetson/runners/${health.jetsonDeviceId}/health")
                .openConnection() as HttpURLConnection
            try {
                conn.requestMethod = "POST"
                conn.connectTimeout = connectTimeoutMs
                conn.readTimeout = readTimeoutMs
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { it.write(body.toString()) }
                conn.responseCode // force the request; response body/errors are not needed for best-effort relay
            } finally {
                conn.disconnect()
            }
        }
    }
}
