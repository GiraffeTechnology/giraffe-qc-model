package com.giraffetechnology.qc.operator.cloud

import org.json.JSONObject
import java.io.File
import java.time.Instant

/** Reconciles durable timeout/offline jobs and retries the original idempotency key. */
class CloudPendingJobReconciler(
    private val store: CloudPendingJobStore,
    private val client: OperatorCloudClient,
) {
    suspend fun runDue(limit: Int = 3) {
        val now = Instant.now()
        store.records()
            .filter { runCatching { Instant.parse(it.nextRetryAt) <= now }.getOrDefault(true) }
            .sortedBy { it.createdAt }
            .take(limit)
            .forEach { record -> reconcile(record) }
    }

    private suspend fun reconcile(record: PendingCloudJob) {
        val manifest = runCatching { JSONObject(record.manifestJson) }.getOrElse {
            store.reschedule(record.jobId, "invalid_queued_manifest", 300)
            return
        }
        val crops = runCatching { restoreCrops(manifest, record.cropPaths) }.getOrElse {
            store.reschedule(record.jobId, "queued_crop_missing", 300)
            return
        }
        var outcome = client.reconcile(record.jobId, manifest, crops)
        if (outcome is CloudSubmitOutcome.Retryable && outcome.code == "job_not_found") {
            outcome = client.submit(record.jobId, manifest, crops)
        }
        when (outcome) {
            is CloudSubmitOutcome.Completed -> store.markRecovered(outcome.recognition)
            is CloudSubmitOutcome.Retryable -> store.reschedule(record.jobId, outcome.code)
            is CloudSubmitOutcome.Rejected -> store.reschedule(record.jobId, outcome.code, 300)
        }
    }

    private fun restoreCrops(manifest: JSONObject, paths: List<String>): List<EncodedCrop> {
        val byName = paths.associateBy { File(it).nameWithoutExtension }
        val points = manifest.getJSONArray("points")
        return (0 until points.length()).map { index ->
            val point = points.getJSONObject(index)
            val cropId = point.getString("crop_id")
            val path = requireNotNull(byName[cropId]) { "queued_crop_missing:$cropId" }
            val region = point.getJSONObject("region_in_capture")
            EncodedCrop(
                cropId = cropId,
                pointCode = point.getString("point_code"),
                bytes = File(path).readBytes(),
                widthPx = point.getInt("width_px"),
                heightPx = point.getInt("height_px"),
                sha256 = point.getString("crop_sha256"),
                region = NormalizedRegion(
                    x = region.getDouble("x"),
                    y = region.getDouble("y"),
                    w = region.getDouble("w"),
                    h = region.getDouble("h"),
                ),
            )
        }
    }
}
