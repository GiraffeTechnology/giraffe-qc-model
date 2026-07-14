package com.giraffetechnology.qc.operator.cloud

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CloudPipelineTest {
    @Test fun `compression profile enforces 200KB hard ceiling`() {
        assertFails { CompressionProfile("x", 204_801, 704, 82) }
        assertEquals(204_800, CompressionProfile("x", 204_800, 704, 82).maxCropBytes)
    }

    @Test fun `region parser rejects full frame and accepts one normalized region`() {
        assertFails { CloudCropEncoder.parseRegion("""{"x":0,"y":0,"w":1,"h":1}""") }
        val region = CloudCropEncoder.parseRegion("""[{"image_id":"p","x":0.1,"y":0.2,"w":0.3,"h":0.4}]""")
        assertEquals(0.1, region.x, 0.0)
        assertEquals(0.4, region.h, 0.0)
    }

    @Test fun `three slow wifi samples switch to healthy cellular`() {
        val policy = NetworkPolicy()
        repeat(3) { i -> policy.observe(LinkSample(OperatorNetwork.WIFI, 3.0, 50, 0.0, i.toLong())) }
        val decision = policy.observe(LinkSample(OperatorNetwork.CELLULAR, 7.0, 70, 0.1, 4))
        assertEquals(OperatorNetwork.CELLULAR, decision.selected)
        assertTrue(decision.switched)
    }

    @Test fun `network selection is locked for active job and switch is deferred`() {
        val policy = NetworkPolicy(NetworkPolicyConfig(sampleWindowSize = 1))
        policy.observe(LinkSample(OperatorNetwork.WIFI, 8.0, 30, 0.0, 0))
        assertEquals(OperatorNetwork.WIFI, policy.beginJob())
        policy.observe(LinkSample(OperatorNetwork.WIFI, 1.0, 400, 10.0, 1))
        policy.observe(LinkSample(OperatorNetwork.CELLULAR, 8.0, 50, 0.0, 2))
        assertEquals(OperatorNetwork.WIFI, policy.currentNetwork())
        assertTrue(policy.switchDeferredUntilJobEnd())
        assertEquals(OperatorNetwork.CELLULAR, policy.endJob().selected)
    }

    @Test fun `canonical json sorts keys recursively`() {
        val input = JSONObject().put("z", JSONArray().put(JSONObject().put("b", 2).put("a", 1))).put("a", true)
        assertEquals("{\"a\":true,\"z\":[{\"a\":1,\"b\":2}]}", CloudInferenceClient.canonicalJson(input))
    }

    private fun assertFails(block: () -> Unit) {
        try { block(); fail("expected failure") } catch (_: IllegalArgumentException) { }
    }
}
