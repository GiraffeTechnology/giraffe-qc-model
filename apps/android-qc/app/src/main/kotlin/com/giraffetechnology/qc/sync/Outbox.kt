package com.giraffetechnology.qc.sync

/**
 * Result outbox (Pad → Server) for Task 03.
 *
 * Completed inspection jobs queue locally during offline production and upload in
 * batches during a sync window. Uploads are idempotent (client-generated
 * [OutboxJob.jobUuid]; the server dedupes) and resumable (uploaded jobs are
 * marked done; a network failure leaves the rest pending for the next window).
 * The outbox never blocks or alters inspection operation.
 */
data class OutboxCheckpoint(
    val detectionPointId: String,
    val result: String,
    val observedValue: String? = null,
    val confidence: Float = 1.0f,
    val notes: String? = null,
)

data class OutboxMedia(
    val localPath: String? = null,
    val sha256: String? = null,
    val angle: String? = null,
    val viewType: String? = null,
)

data class OutboxJob(
    val jobUuid: String,
    val tenantId: String,
    val skuId: String,
    val activeStandardRevisionId: String,
    val overallResult: String,
    val createdBy: String? = null,
    val jobRef: String? = null,
    val notes: String? = null,
    val startedAt: String? = null,
    val completedAt: String? = null,
    val checkpoints: List<OutboxCheckpoint> = emptyList(),
    val media: List<OutboxMedia> = emptyList(),
    val status: String = "pending",   // pending | uploaded | failed
    val attempts: Int = 0,
)

data class OutboxCounts(
    val pending: Int,
    val uploaded: Int,
    val failed: Int,
    val lastSyncAtMs: Long?,
)

interface OutboxStore {
    fun enqueue(job: OutboxJob)
    fun pending(limit: Int): List<OutboxJob>
    fun markUploaded(jobUuid: String)
    fun markFailed(jobUuid: String, reason: String)
    fun counts(): OutboxCounts
    fun setLastSyncAt(tsMs: Long)
}

/** Per-job server outcome returned by [BundleSyncClient.uploadBatch]. */
data class UploadJobOutcome(val jobUuid: String, val status: String, val reason: String? = null)

data class UploadSummary(
    val uploaded: Int,
    val duplicate: Int,
    val rejected: Int,
    val remainingPending: Int,
)

/**
 * Drains the outbox in batches. A server "created" or "duplicate" both mean the
 * job is durably on the server → mark uploaded (idempotent). "rejected" → mark
 * failed (retried on a later window only if re-enqueued). A thrown network error
 * stops the drain with the remainder still pending (resumable).
 */
class OutboxUploader(
    private val store: OutboxStore,
    private val client: BundleSyncClient,
    private val batchSize: Int = 20,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    suspend fun sync(tenantId: String): UploadSummary {
        var uploaded = 0
        var duplicate = 0
        var rejected = 0
        while (true) {
            val batch = store.pending(batchSize)
            if (batch.isEmpty()) break
            val outcomes = client.uploadBatch(tenantId, batch) // may throw on network failure
            for (o in outcomes) {
                when (o.status) {
                    "created" -> { store.markUploaded(o.jobUuid); uploaded++ }
                    "duplicate" -> { store.markUploaded(o.jobUuid); duplicate++ }
                    else -> { store.markFailed(o.jobUuid, o.reason ?: "rejected"); rejected++ }
                }
            }
            // Guard against a client that returns no actionable outcomes for a
            // non-empty batch (would otherwise loop forever).
            if (outcomes.isEmpty()) break
        }
        store.setLastSyncAt(clock())
        return UploadSummary(uploaded, duplicate, rejected, store.counts().pending)
    }
}
