package com.giraffetechnology.qc.jetson

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakeTransport(
    private val getResponses: MutableMap<String, JetsonHttpResponse> = mutableMapOf(),
    private val postResponses: MutableMap<String, JetsonHttpResponse> = mutableMapOf(),
    private val getShouldThrow: Boolean = false,
) : JetsonHttpTransport {
    var lastPostBody: String? = null
        private set

    override fun get(url: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse {
        if (getShouldThrow) return JetsonHttpResponse(-1, null)
        return getResponses[url] ?: JetsonHttpResponse(404, null)
    }

    override fun post(url: String, body: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse {
        lastPostBody = body
        return postResponses[url] ?: JetsonHttpResponse(404, null)
    }
}

class JetsonLanClientTest {

    private fun client(transport: FakeTransport) = JetsonLanClient(transport, 100, 100)

    @Test
    fun `health returns null on unreachable`() {
        val c = client(FakeTransport(getShouldThrow = true))
        assertNull(c.health("http://10.0.0.5:8600"))
    }

    @Test
    fun `health parses a full response including mock flag`() {
        val body = JSONObject()
            .put("service_up", true)
            .put("model_loaded", true)
            .put("temperature_c", 61.5)
            .put("throttling", false)
            .put("disk_free_percent", 72.0)
            .put("last_inference_latency_ms", 340)
            .put("readiness_state", "jetson_ready")
            .put("jetson_device_id", "jetson-a1b2")
            .put("agent_version", "0.2.0")
            .put("adapter_name", "mock")
            .put("model_name", "mock-deterministic")
            .put("mock", true)
            .toString()
        val transport = FakeTransport(getResponses = mutableMapOf("http://10.0.0.5:8600/health" to JetsonHttpResponse(200, body)))
        val health = client(transport).health("http://10.0.0.5:8600")
        assertEquals(true, health?.serviceUp)
        assertEquals(true, health?.modelLoaded)
        assertEquals(JetsonReadinessState.READY, health?.readinessState)
        assertEquals(true, health?.isMock)
        assertEquals("jetson-a1b2", health?.jetsonDeviceId)
        assertEquals(340, health?.lastInferenceLatencyMs)
    }

    @Test
    fun `health defaults mock to false when field absent (old runner)`() {
        val body = JSONObject().put("service_up", true).put("model_loaded", true).put("readiness_state", "jetson_ready").toString()
        val transport = FakeTransport(getResponses = mutableMapOf("http://h:8600/health" to JetsonHttpResponse(200, body)))
        assertEquals(false, client(transport).health("http://h:8600")?.isMock)
    }

    @Test
    fun `pairUsb returns Success on 200`() {
        val body = JSONObject()
            .put("jetson_device_id", "jetson-1")
            .put("jetson_pubkey", "pub-1")
            .put("pair_key", "key-1")
            .put("pairing_path", "usb")
            .toString()
        val transport = FakeTransport(postResponses = mutableMapOf("http://h:8600/pair/usb" to JetsonHttpResponse(200, body)))
        val outcome = client(transport).pairUsb("http://h:8600", "pad-1", "pub-1")
        assertTrue(outcome is JetsonLanClient.PairingOutcome.Success)
        val success = outcome as JetsonLanClient.PairingOutcome.Success
        assertEquals("jetson-1", success.handshake.jetsonDeviceId)
        assertEquals("key-1", success.handshake.pairKey)
    }

    @Test
    fun `pairWifi returns Rejected on 403 with detail`() {
        val body = JSONObject().put("detail", "pairing_window_closed").toString()
        val transport = FakeTransport(postResponses = mutableMapOf("http://h:8600/pair/wifi" to JetsonHttpResponse(403, body)))
        val outcome = client(transport).pairWifi("http://h:8600", "pad-1", "pub-1", "0000-0000-0000-0000")
        assertTrue(outcome is JetsonLanClient.PairingOutcome.Rejected)
        assertEquals("pairing_window_closed", (outcome as JetsonLanClient.PairingOutcome.Rejected).reason)
    }

    @Test
    fun `pairUsb returns Unreachable when transport reports -1`() {
        val transport = object : JetsonHttpTransport {
            override fun get(url: String, connectTimeoutMs: Int, readTimeoutMs: Int) = JetsonHttpResponse(-1, null)
            override fun post(url: String, body: String, connectTimeoutMs: Int, readTimeoutMs: Int) = JetsonHttpResponse(-1, null)
        }
        val outcome = JetsonLanClient(transport, 100, 100).pairUsb("http://h:8600", "pad-1", "pub-1")
        assertTrue(outcome is JetsonLanClient.PairingOutcome.Unreachable)
    }

    @Test
    fun `infer signs the request and returns parsed per-point results`() {
        val respBody = JSONObject()
            .put("job_id", "j1")
            .put(
                "per_point_results",
                org.json.JSONArray().put(
                    JSONObject().put("point_code", "cp1").put("result", "pass").put("confidence", 0.95).put("evidence", "ok"),
                ),
            )
            .toString()
        val transport = FakeTransport(postResponses = mutableMapOf("http://h:8600/infer" to JetsonHttpResponse(200, respBody)))
        val request = JetsonInferenceRequest(
            jobId = "j1",
            standardRevisionId = "r1",
            image = "data:image/jpeg;base64,abc",
            detectionPoints = listOf(JetsonDetectionPointSpec(pointCode = "cp1")),
        )
        val outcome = client(transport).infer("http://h:8600", "pad-1", "key-1", request)
        assertTrue(outcome is JetsonLanClient.InferOutcome.Success)
        val response = (outcome as JetsonLanClient.InferOutcome.Success).response
        assertEquals("j1", response.jobId)
        assertEquals("pass", response.perPointResults[0].result)

        // The envelope actually posted must carry a real hex signature (not
        // empty/placeholder) computed from the canonical request.
        val posted = JSONObject(transport.lastPostBody!!)
        assertEquals("pad-1", posted.getString("pad_device_id"))
        assertEquals(64, posted.getString("signature").length)
        assertEquals(
            signJetsonRequest("key-1", request.toJson()),
            posted.getString("signature"),
        )
    }

    @Test
    fun `infer returns Rejected with detail on non-200`() {
        val body = JSONObject().put("detail", "runtime_not_ready").toString()
        val transport = FakeTransport(postResponses = mutableMapOf("http://h:8600/infer" to JetsonHttpResponse(503, body)))
        val request = JetsonInferenceRequest(jobId = "j1", standardRevisionId = "r1", image = "x", detectionPoints = listOf(JetsonDetectionPointSpec(pointCode = "cp1")))
        val outcome = client(transport).infer("http://h:8600", "pad-1", "key-1", request)
        assertTrue(outcome is JetsonLanClient.InferOutcome.Rejected)
        assertEquals("runtime_not_ready", (outcome as JetsonLanClient.InferOutcome.Rejected).reason)
    }
}
