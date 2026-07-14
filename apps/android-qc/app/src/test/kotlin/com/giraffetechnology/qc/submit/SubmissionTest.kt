package com.giraffetechnology.qc.submit

import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask
import com.giraffetechnology.qc.sku.Sku
import com.giraffetechnology.qc.sku.SkuResolutionMethod
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Outbox idempotency + uploader drain + submission provenance (§9). */
class SubmissionTest {

    private fun task(rev: String? = "rev-9", bundle: String? = "20") = QcTask(
        sku = Sku(id = "sku-1", itemNumber = "ITEM-001", name = "Widget"),
        confirmedByUser = true,
        resolvedBy = SkuResolutionMethod.MANUAL_ITEM_NUMBER,
        activeStandardRevisionId = rev,
        bundleVersion = bundle,
    )

    private val result = PadInspectionResult(
        overallResult = "ACCEPTED",
        reason = "ok",
        modelName = "Qwen3-VL-2B-Instruct-MNN",
        localOnly = true,
        cloudInferenceUsed = false,
        capturedImagePath = "/sdcard/cap/1.jpg",
    )

    private fun submission(id: String, rev: String? = "rev-9", bundle: String? = "20") =
        ResultSubmission.from(task(rev, bundle), result, HumanDecision.PASS, id, 1000L)

    @Test fun `submission carries standard revision id and bundle version`() {
        val s = submission("job-1")
        assertEquals("rev-9", s.standardRevisionId)
        assertEquals("20", s.bundleVersion)
        assertEquals(HumanDecision.PASS, s.humanDecision)
        assertEquals("ACCEPTED", s.modelResult)
    }

    @Test fun `outbox enqueue is idempotent on clientJobId`() = runTest {
        val outbox = PadOutbox(InMemoryOutboxStore())
        assertTrue(outbox.enqueue(submission("job-1")))
        assertFalse("duplicate clientJobId must not re-enqueue", outbox.enqueue(submission("job-1")))
        assertEquals(1, outbox.pendingCount())
    }

    @Test fun `uploader drains pending and marks accepted uploaded`() = runTest {
        val outbox = PadOutbox(InMemoryOutboxStore())
        outbox.enqueue(submission("job-1"))
        outbox.enqueue(submission("job-2"))

        val client = object : SubmissionClient {
            var seen: List<ResultSubmission>? = null
            override suspend fun submit(batch: List<ResultSubmission>): SubmitResult {
                seen = batch
                return SubmitResult.Accepted(batch.map { it.clientJobId })
            }
        }
        val outcome = OutboxUploader(outbox, client).uploadPending()

        assertEquals(2, outcome.uploadedCount)
        assertEquals(0, outbox.pendingCount())
        // The batch actually carried the revision/bundle provenance.
        assertTrue(client.seen!!.all { it.standardRevisionId == "rev-9" && it.bundleVersion == "20" })
    }

    @Test fun `failed upload leaves everything pending for retry`() = runTest {
        val outbox = PadOutbox(InMemoryOutboxStore())
        outbox.enqueue(submission("job-1"))
        val client = object : SubmissionClient {
            override suspend fun submit(batch: List<ResultSubmission>) = SubmitResult.Failed("HTTP 503")
        }
        val outcome = OutboxUploader(outbox, client).uploadPending()
        assertEquals(0, outcome.uploadedCount)
        assertEquals("HTTP 503", outcome.error)
        assertEquals(1, outbox.pendingCount())
    }

    @Test fun `uploading with nothing pending is a no-op`() = runTest {
        val outbox = PadOutbox(InMemoryOutboxStore())
        val client = object : SubmissionClient {
            var called = false
            override suspend fun submit(batch: List<ResultSubmission>): SubmitResult {
                called = true; return SubmitResult.Accepted(emptyList())
            }
        }
        val outcome = OutboxUploader(outbox, client).uploadPending()
        assertEquals(0, outcome.uploadedCount)
        assertFalse(client.called)
    }

    @Test fun `encodeBody includes revision and bundle, parseAcceptedIds falls back to submitted`() {
        val batch = listOf(submission("job-1"), submission("job-2"))
        val body = HttpSubmissionClient.encodeBody(batch)
        assertTrue(body.contains("standard_revision_id"))
        assertTrue(body.contains("bundle_version"))
        assertTrue(body.contains("rev-9"))

        // Empty response body → all submitted ids treated as accepted (idempotent server).
        assertEquals(listOf("job-1", "job-2"), HttpSubmissionClient.parseAcceptedIds("", batch))
        // Explicit accepted_job_ids honored.
        assertEquals(
            listOf("job-1"),
            HttpSubmissionClient.parseAcceptedIds("""{"accepted_job_ids":["job-1"]}""", batch),
        )
    }

    @Test fun `S4 body carries cloud point results unchanged for server recomputation`() {
        val s4Submission = submission("job-1").copy(
            cloudJobId = "cloud-1",
            pointResultsJson = """[{"point_code":"p1","result":"pass","confidence":0.9}]""",
            timingJson = """{"capture_confirmed_at":"t0","verdict_rendered_at":"t1"}""",
        )
        val json = org.json.JSONObject(HttpSubmissionClient.encodeS4Body(s4Submission))
        assertEquals("cloud-1", json.getString("job_ref"))
        assertEquals("p1", json.getJSONArray("checkpoints").getJSONObject(0).getString("checkpoint_id"))
        assertEquals("pass", json.getJSONArray("checkpoints").getJSONObject(0).getString("result"))
        assertEquals(0.9, json.getJSONArray("cloud_recognition").getJSONObject(0).getDouble("confidence"), 0.0)
    }
}
