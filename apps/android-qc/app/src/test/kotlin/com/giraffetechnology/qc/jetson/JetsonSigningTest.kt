package com.giraffetechnology.qc.jetson

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Cross-language verification: the expected canonical string and signature
 * below were computed with real Python (`json.dumps(..., sort_keys=True,
 * separators=(",",":"))` + `hmac.new(..., hashlib.sha256).hexdigest()`),
 * matching `jetson_runner/app/signing.py` exactly -- not derived from the
 * Kotlin implementation under test. If this test ever needs updating,
 * regenerate the vector from Python, not by copying whatever Kotlin prints.
 */
class JetsonSigningTest {

    private fun referencePayload(): JSONObject {
        val point = JSONObject()
            .put("point_code", "cp1")
            .put("label", "core")
            .put("description", "")
            .put("method_hint", "")
            .put("expected_value", "")
            .put("pass_criteria", "")
            .put("severity", "major")
            .put("regions", JSONArray())
        return JSONObject()
            .put("job_id", "j1")
            .put("standard_revision_id", "r1")
            .put("bundle_version", "")
            .put("image", "data:image/jpeg;base64,abc")
            .put("detection_points", JSONArray().put(point))
    }

    @Test
    fun `canonical json matches python json dumps sort_keys separators`() {
        val expected =
            "{\"bundle_version\":\"\",\"detection_points\":[{\"description\":\"\"," +
                "\"expected_value\":\"\",\"label\":\"core\",\"method_hint\":\"\"," +
                "\"pass_criteria\":\"\",\"point_code\":\"cp1\",\"regions\":[]," +
                "\"severity\":\"major\"}],\"image\":\"data:image/jpeg;base64,abc\"," +
                "\"job_id\":\"j1\",\"standard_revision_id\":\"r1\"}"
        assertEquals(expected, canonicalJson(referencePayload()))
    }

    @Test
    fun `hmac signature matches python hmac hexdigest for the same key and payload`() {
        val expectedSignature = "aeaf4fe1c3d8a8a1a8d459db30b13f6ce650e69c84dc40693597ba7c2e7fa4ad"
        assertEquals(expectedSignature, signJetsonRequest("testkey", referencePayload()))
    }

    @Test
    fun `forward slash is not escaped, matching python default`() {
        val obj = JSONObject().put("image", "data:image/jpeg;base64,a/b+c==")
        assertEquals("{\"image\":\"data:image/jpeg;base64,a/b+c==\"}", canonicalJson(obj))
    }

    @Test
    fun `non-ascii characters are escaped as uXXXX matching ensure_ascii=True`() {
        val obj = JSONObject().put("label", "花芯")
        assertEquals("{\"label\":\"\\u82b1\\u82af\"}", canonicalJson(obj))
    }

    @Test
    fun `key order does not affect the canonical output`() {
        val a = JSONObject().put("b", 1).put("a", 2)
        val b = JSONObject().put("a", 2).put("b", 1)
        assertEquals(canonicalJson(a), canonicalJson(b))
    }

    @Test
    fun `signature changes if a single field changes`() {
        val payload = referencePayload()
        val sig1 = signJetsonRequest("testkey", payload)
        payload.put("job_id", "j2")
        val sig2 = signJetsonRequest("testkey", payload)
        assert(sig1 != sig2)
    }
}
