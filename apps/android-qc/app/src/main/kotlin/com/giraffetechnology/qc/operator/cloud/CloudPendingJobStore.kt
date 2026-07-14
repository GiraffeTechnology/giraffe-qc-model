package com.giraffetechnology.qc.operator.cloud

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Durable queue: only bounded crops and minimal signed manifest metadata are stored. */
class CloudPendingJobStore(context: Context) {
    private val root = File(context.filesDir, "operator_cloud_pending")

    @Synchronized
    fun enqueue(job: PendingCloudJob, crops: List<EncodedCrop>) {
        val dir = File(root, job.jobId).apply { mkdirs() }
        val cropPaths = crops.map { crop ->
            File(dir, "${crop.cropId}.jpg").also { it.writeBytes(crop.bytes) }.absolutePath
        }
        val json = JSONObject()
            .put("job_id", job.jobId).put("created_at", job.createdAt)
            .put("retry_count", job.retryCount).put("next_retry_at", job.nextRetryAt)
            .put("selected_network", job.selectedNetwork).put("last_error_code", job.lastErrorCode)
            .put("manifest", JSONObject(job.manifestJson)).put("crop_paths", JSONArray(cropPaths))
        File(dir, "job.json").writeText(json.toString())
    }

    @Synchronized fun pendingCount(): Int = root.listFiles()?.count { File(it, "job.json").isFile } ?: 0
    @Synchronized fun oldestPendingSince(): String? = records().minByOrNull { it.createdAt }?.createdAt

    @Synchronized
    fun records(): List<PendingCloudJob> = root.listFiles().orEmpty().mapNotNull { dir ->
        runCatching {
            val json = JSONObject(File(dir, "job.json").readText())
            val paths = json.getJSONArray("crop_paths")
            PendingCloudJob(
                jobId = json.getString("job_id"), createdAt = json.getString("created_at"),
                retryCount = json.getInt("retry_count"), nextRetryAt = json.getString("next_retry_at"),
                selectedNetwork = json.getString("selected_network"),
                lastErrorCode = json.getString("last_error_code"),
                manifestJson = json.getJSONObject("manifest").toString(),
                cropPaths = (0 until paths.length()).map { paths.getString(it) },
            )
        }.getOrNull()
    }

    @Synchronized fun remove(jobId: String) { File(root, jobId).deleteRecursively() }
}
