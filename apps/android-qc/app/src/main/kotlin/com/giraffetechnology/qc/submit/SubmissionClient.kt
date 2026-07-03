package com.giraffetechnology.qc.submit

/**
 * Uploads a batch of completed results to the Server (S6 §9). Implementations
 * post to the sync endpoint; the Server dedupes idempotently on
 * [ResultSubmission.clientJobId].
 */
interface SubmissionClient {
    suspend fun submit(batch: List<ResultSubmission>): SubmitResult
}

sealed class SubmitResult {
    /** The Server acknowledged these client job ids as stored (or already stored). */
    data class Accepted(val acceptedJobIds: List<String>) : SubmitResult()
    /** The upload failed as a whole (network/server); nothing is marked uploaded. */
    data class Failed(val reason: String) : SubmitResult()
}

/**
 * Drains the [PadOutbox] to the Server. Only client job ids the Server accepted
 * are marked uploaded, so a partial/failed upload safely retries the rest next
 * time. Idempotent end to end: re-running when nothing is pending is a no-op, and
 * the Server ignores duplicates.
 */
class OutboxUploader(
    private val outbox: PadOutbox,
    private val client: SubmissionClient,
) {
    suspend fun uploadPending(): UploadOutcome {
        val pending = outbox.pending()
        if (pending.isEmpty()) return UploadOutcome(uploadedCount = 0, error = null)

        return when (val result = client.submit(pending)) {
            is SubmitResult.Accepted -> {
                result.acceptedJobIds.forEach { outbox.markUploaded(it) }
                UploadOutcome(uploadedCount = result.acceptedJobIds.size, error = null)
            }
            is SubmitResult.Failed ->
                UploadOutcome(uploadedCount = 0, error = result.reason)
        }
    }
}

data class UploadOutcome(val uploadedCount: Int, val error: String?)
