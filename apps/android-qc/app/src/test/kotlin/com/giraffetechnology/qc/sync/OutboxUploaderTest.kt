package com.giraffetechnology.qc.sync

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Outbox upload: dedupe, resume-after-failure, rejection handling (Task 03, acceptance #7/#8). */
class OutboxUploaderTest {

    private fun job(uuid: String) = OutboxJob(
        jobUuid = uuid, tenantId = "default", skuId = "sku-a",
        activeStandardRevisionId = "sku-a-rev1", overallResult = "pass",
        checkpoints = listOf(OutboxCheckpoint("sku-a-dp0", "pass", confidence = 0.9f)),
    )

    @Test fun `enqueue is idempotent`() {
        val store = InMemoryOutboxStore()
        store.enqueue(job("j1"))
        store.enqueue(job("j1"))
        assertEquals(1, store.counts().pending)
    }

    @Test fun `sync uploads pending then reports counts`() = runTest {
        val store = InMemoryOutboxStore()
        store.enqueue(job("j1")); store.enqueue(job("j2"))
        val client = FakeSyncClient()
        val summary = OutboxUploader(store, client, batchSize = 10).sync("default")
        assertEquals(2, summary.uploaded)
        assertEquals(0, store.counts().pending)
        assertEquals(2, store.counts().uploaded)
    }

    @Test fun `re-upload of already-sent job is deduped by server`() = runTest {
        val store = InMemoryOutboxStore()
        val client = FakeSyncClient()
        store.enqueue(job("j1"))
        OutboxUploader(store, client, batchSize = 10).sync("default")
        // Re-enqueue same UUID (e.g. operator re-runs) → still one job; server dedupes.
        store.enqueue(job("j1"))
        assertEquals(0, store.counts().pending) // already uploaded, not re-queued
    }

    @Test fun `rejected job is marked failed not uploaded`() = runTest {
        val store = InMemoryOutboxStore()
        store.enqueue(job("good")); store.enqueue(job("bad"))
        val client = FakeSyncClient(rejectUuids = setOf("bad"))
        val summary = OutboxUploader(store, client, batchSize = 10).sync("default")
        assertEquals(1, summary.uploaded)
        assertEquals(1, summary.rejected)
        assertEquals(1, store.counts().uploaded)
        assertEquals(1, store.counts().failed)
    }

    @Test fun `network failure mid-drain leaves remainder pending (resumable)`() = runTest {
        val store = InMemoryOutboxStore()
        repeat(5) { store.enqueue(job("j$it")) }
        // batchSize 2: first batch (2 jobs) succeeds and is marked; the second batch
        // throws before any outcome, so those jobs stay pending (atomic per batch).
        val flaky = FakeSyncClient(failAfter = 2)
        val ex = runCatching { OutboxUploader(store, flaky, batchSize = 2).sync("default") }.exceptionOrNull()
        assertTrue(ex is java.io.IOException)
        assertEquals(2, store.counts().uploaded)
        assertEquals(3, store.counts().pending) // resumable next window

        // Next window: a healthy client drains the remaining 3.
        val healthy = FakeSyncClient()
        val summary = OutboxUploader(store, healthy, batchSize = 10).sync("default")
        assertEquals(3, summary.uploaded)
        assertEquals(0, store.counts().pending)
        assertEquals(5, store.counts().uploaded)
    }
}
