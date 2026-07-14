package com.giraffetechnology.qc.submit

import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask

/**
 * The operator's final human decision on an inspected item (S6 §9). The model
 * never finalizes — a person confirms accept / reject or defers to review.
 */
enum class HumanDecision(val wire: String) {
    PASS("pass"),
    FAIL("fail"),
    REVIEW_REQUIRED("review_required");

    companion object {
        fun fromWire(v: String): HumanDecision? = entries.firstOrNull { it.wire == v }
    }
}

/**
 * A completed QC result queued for upload to the Server (S6 §9).
 *
 * Carries the **standard_revision_id** and **bundle_version** the inspection ran
 * against so the Server (S4) can recompute the verdict against exactly that
 * standard. [clientJobId] is the client-generated idempotency key: the Server
 * dedupes on it, so re-uploading the same result is a no-op.
 */
data class ResultSubmission(
    val clientJobId: String,
    val tenantId: String,
    val skuId: String,
    val itemNumber: String,
    /** The standard revision the inspection used (§9). */
    val standardRevisionId: String?,
    /** The bundle version the standard was installed from (§9). */
    val bundleVersion: String?,
    /** The model's recommendation (ACCEPTED / NOT_ACCEPTED / review_required / MNN_PENDING). */
    val modelResult: String,
    /** The operator's binding final decision. */
    val humanDecision: HumanDecision,
    val reason: String,
    val modelName: String,
    val capturedImagePath: String?,
    val createdAtEpochMs: Long,
    val cloudJobId: String? = null,
    val pointResultsJson: String? = null,
    val timingJson: String? = null,
) {
    companion object {
        /**
         * Build a submission from the confirmed task, the model result, and the
         * operator's decision. The standard revision id and bundle version come
         * from the task so they always reflect the standard actually used.
         */
        fun from(
            task: QcTask,
            result: PadInspectionResult,
            decision: HumanDecision,
            clientJobId: String,
            createdAtEpochMs: Long,
        ): ResultSubmission = ResultSubmission(
            clientJobId = clientJobId,
            tenantId = task.tenantId,
            skuId = task.sku.id,
            itemNumber = task.sku.itemNumber,
            standardRevisionId = task.activeStandardRevisionId,
            bundleVersion = task.bundleVersion,
            modelResult = result.overallResult,
            humanDecision = decision,
            reason = result.reason,
            modelName = result.modelName,
            capturedImagePath = result.capturedImagePath,
            createdAtEpochMs = createdAtEpochMs,
            cloudJobId = result.cloudJobId,
            pointResultsJson = result.pointResultsJson,
            timingJson = org.json.JSONObject(result.timing).toString(),
        )
    }
}
