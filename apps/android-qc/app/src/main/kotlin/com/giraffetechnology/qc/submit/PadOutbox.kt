package com.giraffetechnology.qc.submit

/**
 * A queued result plus its upload state.
 */
data class OutboxEntry(
    val submission: ResultSubmission,
    val uploaded: Boolean,
)

/**
 * Persistence port for the Pad outbox. Enqueue is idempotent on
 * [ResultSubmission.clientJobId]: a repeated enqueue of the same job returns
 * false and does not duplicate the row.
 */
interface OutboxStore {
    /** Returns true if newly stored, false if a row with the same clientJobId exists. */
    suspend fun enqueue(entry: OutboxEntry): Boolean
    /** Entries not yet uploaded, oldest first. */
    suspend fun pending(): List<OutboxEntry>
    /** All entries (pending + uploaded), oldest first. */
    suspend fun all(): List<OutboxEntry>
    suspend fun markUploaded(clientJobId: String)
}

/**
 * The Pad-side result outbox (S6 §9). Inspection runs offline, so completed
 * results are written here and drained to the Server later by [OutboxUploader].
 * Because inspection can never touch the network, nothing on the QC path depends
 * on connectivity — results simply accumulate and sync when a window opens.
 */
class PadOutbox(private val store: OutboxStore) {

    /** Queue a completed result. Idempotent on clientJobId. */
    suspend fun enqueue(submission: ResultSubmission): Boolean =
        store.enqueue(OutboxEntry(submission = submission, uploaded = false))

    suspend fun pending(): List<ResultSubmission> = store.pending().map { it.submission }

    suspend fun pendingCount(): Int = store.pending().size

    suspend fun all(): List<OutboxEntry> = store.all()

    suspend fun markUploaded(clientJobId: String) = store.markUploaded(clientJobId)
}
