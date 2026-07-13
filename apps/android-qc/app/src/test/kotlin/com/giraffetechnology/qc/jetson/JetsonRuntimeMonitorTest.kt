package com.giraffetechnology.qc.jetson

import com.giraffetechnology.qc.sku.MnnRuntimeState
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class JetsonRuntimeMonitorTest {

    private fun healthBody(serviceUp: Boolean, modelLoaded: Boolean, readinessState: String, mock: Boolean = true): String =
        JSONObject()
            .put("service_up", serviceUp)
            .put("model_loaded", modelLoaded)
            .put("readiness_state", readinessState)
            .put("jetson_device_id", "jetson-1")
            .put("agent_version", "0.2.0")
            .put("mock", mock)
            .toString()

    private class FakeTransport(private val healthResponse: JetsonHttpResponse) : JetsonHttpTransport {
        override fun get(url: String, connectTimeoutMs: Int, readTimeoutMs: Int) = healthResponse
        override fun post(url: String, body: String, connectTimeoutMs: Int, readTimeoutMs: Int) = JetsonHttpResponse(404, null)
    }

    @Test
    fun `unpaired maps to NotReady`() = runBlocking {
        val store = InMemoryJetsonPairingStore()
        val monitor = JetsonRuntimeMonitor(store, JetsonLanClient(FakeTransport(JetsonHttpResponse(-1, null)), 100, 100))
        monitor.pollOnce()
        assertEquals(MnnRuntimeState.NotReady, monitor.runtimeState.value)
        assertEquals(JetsonReadinessState.UNREACHABLE, monitor.jetsonState.value.readiness)
        assertFalse(monitor.inferenceVerified)
    }

    @Test
    fun `paired but unreachable maps to NotReady`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply {
            savePairing("10.0.0.5", JetsonPairingStore.DEFAULT_PORT, "jetson-1", "key-1", "usb")
        }
        val monitor = JetsonRuntimeMonitor(store, JetsonLanClient(FakeTransport(JetsonHttpResponse(-1, null)), 100, 100))
        monitor.pollOnce()
        assertEquals(MnnRuntimeState.NotReady, monitor.runtimeState.value)
        assertEquals(JetsonReadinessState.UNREACHABLE, monitor.jetsonState.value.readiness)
    }

    @Test
    fun `paired, reachable, service up but model not loaded maps to Loading`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply {
            savePairing("10.0.0.5", JetsonPairingStore.DEFAULT_PORT, "jetson-1", "key-1", "usb")
        }
        val body = healthBody(serviceUp = true, modelLoaded = false, readinessState = "jetson_connecting")
        val monitor = JetsonRuntimeMonitor(store, JetsonLanClient(FakeTransport(JetsonHttpResponse(200, body)), 100, 100))
        monitor.pollOnce()
        assertEquals(MnnRuntimeState.Loading, monitor.runtimeState.value)
        assertEquals(JetsonReadinessState.CONNECTING, monitor.jetsonState.value.readiness)
    }

    @Test
    fun `paired, reachable, service up and model loaded maps to Ready`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply {
            savePairing("10.0.0.5", JetsonPairingStore.DEFAULT_PORT, "jetson-1", "key-1", "usb")
        }
        val body = healthBody(serviceUp = true, modelLoaded = true, readinessState = "jetson_ready")
        val monitor = JetsonRuntimeMonitor(store, JetsonLanClient(FakeTransport(JetsonHttpResponse(200, body)), 100, 100))
        monitor.pollOnce()
        assertEquals(MnnRuntimeState.Ready, monitor.runtimeState.value)
        assertEquals(JetsonReadinessState.READY, monitor.jetsonState.value.readiness)
        assertEquals(true, monitor.jetsonState.value.lastHealth?.isMock)
    }

    @Test
    fun `service reports down maps to NotReady even though it answered`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply {
            savePairing("10.0.0.5", JetsonPairingStore.DEFAULT_PORT, "jetson-1", "key-1", "usb")
        }
        val body = healthBody(serviceUp = false, modelLoaded = false, readinessState = "jetson_connecting")
        val monitor = JetsonRuntimeMonitor(store, JetsonLanClient(FakeTransport(JetsonHttpResponse(200, body)), 100, 100))
        monitor.pollOnce()
        assertEquals(MnnRuntimeState.NotReady, monitor.runtimeState.value)
    }

    @Test
    fun `inferenceVerified is hardcoded false -- no hardware validation claimed`() {
        assertFalse(JetsonRuntimeMonitor.JETSON_INFERENCE_VERIFIED)
    }
}
