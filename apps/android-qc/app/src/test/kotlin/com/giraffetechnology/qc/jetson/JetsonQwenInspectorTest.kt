package com.giraffetechnology.qc.jetson

import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.QcPointInput
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * `encodeImageAsDataUri` delegates to `android.util.Base64`, an Android
 * platform API this project's JVM unit tests stub out
 * (`testOptions { unitTests.isReturnDefaultValues = true }`) rather than
 * exercise for real -- these tests cover the aggregation/mapping logic
 * around it, not base64 encoding correctness itself (that's Android
 * platform-tested, not custom code). Uses the same fake-`JetsonHttpTransport`
 * seam as `JetsonLanClientTest` rather than subclassing `JetsonLanClient`
 * (a final class, deliberately not designed to be mocked/subclassed).
 */
class JetsonQwenInspectorTest {

    private class FakeTransport(
        private val inferResponse: JetsonHttpResponse? = null,
        private val inferShouldThrow: Boolean = false,
    ) : JetsonHttpTransport {
        override fun get(url: String, connectTimeoutMs: Int, readTimeoutMs: Int) = JetsonHttpResponse(404, null)
        override fun post(url: String, body: String, connectTimeoutMs: Int, readTimeoutMs: Int): JetsonHttpResponse {
            if (inferShouldThrow) return JetsonHttpResponse(-1, null)
            return inferResponse ?: JetsonHttpResponse(404, null)
        }
    }

    private fun clientReturning(status: Int, body: JSONObject): JetsonLanClient =
        JetsonLanClient(FakeTransport(JetsonHttpResponse(status, body.toString())), 100, 100)

    private fun unreachableClient(): JetsonLanClient = JetsonLanClient(FakeTransport(inferShouldThrow = true), 100, 100)

    private fun successBody(results: List<Triple<String, String, String>>): JSONObject =
        JSONObject().put("job_id", "job-1").put(
            "per_point_results",
            JSONArray(
                results.map { (code, result, evidence) ->
                    JSONObject().put("point_code", code).put("result", result).put("confidence", 0.9).put("evidence", evidence)
                },
            ),
        )

    private fun tempPhoto(): CapturePhotoInput {
        val f = File.createTempFile("capture", ".jpg")
        f.writeBytes(byteArrayOf(1, 2, 3))
        f.deleteOnExit()
        return CapturePhotoInput(photoId = "cap-1", localPath = f.absolutePath)
    }

    private fun points() = listOf(
        QcPointInput(qcPointId = "id-1", qcPointCode = "cp1", name = "core", description = "core centered"),
        QcPointInput(qcPointId = "id-2", qcPointCode = "cp2", name = "count", description = "pearl count"),
    )

    private fun context() = InspectionContext(tenantId = "default", skuId = "sku-1", standardId = "rev-1", inspectionId = "job-1")

    @Test
    fun `throws jetson_not_paired when store has no pairing`() = runBlocking {
        val inspector = JetsonQwenInspector(InMemoryJetsonPairingStore(), JetsonLanClient())
        val ex = kotlin.runCatching {
            inspector.inspect(emptyList(), tempPhoto(), points(), context())
        }.exceptionOrNull()
        assertTrue(ex is IllegalStateException)
        assertEquals("jetson_not_paired", ex?.message)
    }

    @Test
    fun `overall result is fail if any point fails, even if others pass`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply { savePairing("10.0.0.5", 8600, "jetson-1", "key-1", "usb") }
        val client = clientReturning(200, successBody(listOf(Triple("cp1", "pass", "ok"), Triple("cp2", "fail", "defect found"))))
        val output = JetsonQwenInspector(store, client).inspect(emptyList(), tempPhoto(), points(), context())
        assertEquals("fail", output.overallResult)
        assertEquals(2, output.items.size)
    }

    @Test
    fun `uncertain point maps to review_required, never silently pass or fail`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply { savePairing("10.0.0.5", 8600, "jetson-1", "key-1", "usb") }
        val client = clientReturning(200, successBody(listOf(Triple("cp1", "uncertain", "unclear"), Triple("cp2", "pass", "ok"))))
        val output = JetsonQwenInspector(store, client).inspect(emptyList(), tempPhoto(), points(), context())
        assertEquals("review_required", output.overallResult)
        assertEquals("review_required", output.items.first { it.qcPointCode == "cp1" }.result)
    }

    @Test
    fun `all pass maps to pass`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply { savePairing("10.0.0.5", 8600, "jetson-1", "key-1", "usb") }
        val client = clientReturning(200, successBody(listOf(Triple("cp1", "pass", "ok"), Triple("cp2", "pass", "ok"))))
        val output = JetsonQwenInspector(store, client).inspect(emptyList(), tempPhoto(), points(), context())
        assertEquals("pass", output.overallResult)
    }

    @Test
    fun `unreachable outcome throws jetson_unreachable`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply { savePairing("10.0.0.5", 8600, "jetson-1", "key-1", "usb") }
        val ex = kotlin.runCatching {
            JetsonQwenInspector(store, unreachableClient()).inspect(emptyList(), tempPhoto(), points(), context())
        }.exceptionOrNull()
        assertEquals("jetson_unreachable", ex?.message)
    }

    @Test
    fun `rejected outcome propagates the reason, does not silently pass`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply { savePairing("10.0.0.5", 8600, "jetson-1", "key-1", "usb") }
        val client = clientReturning(503, JSONObject().put("detail", "runtime_not_ready"))
        val ex = kotlin.runCatching {
            JetsonQwenInspector(store, client).inspect(emptyList(), tempPhoto(), points(), context())
        }.exceptionOrNull()
        assertEquals("jetson_rejected:runtime_not_ready", ex?.message)
    }

    @Test
    fun `unmatched point code still becomes a result, not dropped`() = runBlocking {
        val store = InMemoryJetsonPairingStore().apply { savePairing("10.0.0.5", 8600, "jetson-1", "key-1", "usb") }
        val client = clientReturning(200, successBody(listOf(Triple("cp-unknown", "pass", "ok"))))
        val output = JetsonQwenInspector(store, client).inspect(emptyList(), tempPhoto(), points(), context())
        assertEquals(1, output.items.size)
        assertEquals("cp-unknown", output.items[0].qcPointCode)
    }
}
