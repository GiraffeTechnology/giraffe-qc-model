package com.giraffetechnology.qc.operator.cloud

import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.FallbackInfo
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.InspectionItemResult
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.QwenInspector
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.util.UUID

/** Provider-neutral cloud contract adapter; the configured model is data, not a product dependency. */
class CloudVlmInspector(
    private val client: OperatorCloudClient,
    private val encoder: CloudCropEncoder,
    private val pendingStore: CloudPendingJobStore,
    private val networkPolicy: NetworkPolicy,
    override val modelName: String,
    private val deadlineMs: Long = 10_000,
) : QwenInspector {
    override val engineName: String = "configured_cloud_vlm"

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = coroutineScope {
        val startNanos = System.nanoTime()
        val captureAt = Instant.now().toString()
        val cvStartedAt = Instant.now().toString()
        val crops = qcPoints.map { point ->
            async { encoder.encode(capturedPhoto.localPath, point.qcPointCode, point.roiJson) }
        }.awaitAll()
        val cvCompletedAt = Instant.now().toString()
        val jobId = "job_${UUID.randomUUID()}"
        val manifest = manifest(jobId, context, qcPoints, crops, captureAt, cvStartedAt, cvCompletedAt)
        val network = networkPolicy.beginJob()
        if (network == OperatorNetwork.NONE) {
            queue(jobId, manifest, crops, network, "no_usable_network")
            networkPolicy.endJob()
            error("pending_upload:$jobId:no_usable_network")
        }
        try {
            var outcome = client.submit(jobId, manifest, crops)
            if (outcome is CloudSubmitOutcome.Retryable && elapsedMs(startNanos) < deadlineMs - 500) {
                outcome = client.submit(jobId, manifest, crops)
            }
            when (outcome) {
                is CloudSubmitOutcome.Completed -> {
                    val recognition = outcome.recognition
                    val now = Instant.now().toString()
                    QwenInspectionOutput(
                        overallResult = recognition.overallResult,
                        engine = engineName,
                        modelName = recognition.modelFamily,
                        confidence = recognition.pointResults.minOfOrNull { it.confidence } ?: 0f,
                        items = recognition.pointResults.map { point ->
                            InspectionItemResult(
                                qcPointId = qcPoints.first { it.qcPointCode == point.pointCode }.qcPointId,
                                qcPointCode = point.pointCode,
                                name = qcPoints.first { it.qcPointCode == point.pointCode }.name,
                                result = if (point.result == "uncertain") "review_required" else point.result,
                                confidence = point.confidence, reason = point.evidence,
                                evidence = buildMap {
                                    put("crop_id", point.cropId)
                                    put("cv_status", point.cvStatus)
                                    point.cvAnalysisJson?.let { put("cv_analysis", JSONObject(it)) }
                                },
                            )
                        },
                        fallback = FallbackInfo(false), summary = "Cloud recognition completed",
                        cloudJobId = jobId,
                        timing = mapOf(
                            "capture_confirmed_at" to captureAt, "cv_started_at" to cvStartedAt,
                            "cv_completed_at" to cvCompletedAt, "response_received_at" to now,
                            "verdict_rendered_at" to now, "elapsed_ms" to elapsedMs(startNanos).toString(),
                            "network" to network.wire,
                        ),
                    )
                }
                is CloudSubmitOutcome.Retryable -> {
                    queue(jobId, manifest, crops, network, outcome.code)
                    error("pending_upload:$jobId:${outcome.code}")
                }
                is CloudSubmitOutcome.Rejected -> error("cloud_rejected:${outcome.code}")
            }
        } finally { networkPolicy.endJob() }
    }

    internal fun manifest(
        jobId: String, context: InspectionContext, points: List<QcPointInput>, crops: List<EncodedCrop>,
        captureAt: String, cvStartedAt: String, cvCompletedAt: String,
    ): JSONObject = buildCloudManifest(
        jobId, context, points, crops, captureAt, cvStartedAt, cvCompletedAt, deadlineMs,
    )

    private fun queue(jobId: String, manifest: JSONObject, crops: List<EncodedCrop>, network: OperatorNetwork, code: String) {
        val now = Instant.now()
        pendingStore.enqueue(
            PendingCloudJob(jobId, now.toString(), 2, now.plusSeconds(30).toString(), network.wire, code, manifest.toString(), emptyList()),
            crops,
        )
    }

    private fun elapsedMs(startNanos: Long): Long = (System.nanoTime() - startNanos) / 1_000_000
}

internal fun buildCloudManifest(
    jobId: String, context: InspectionContext, points: List<QcPointInput>, crops: List<EncodedCrop>,
    captureAt: String, cvStartedAt: String, cvCompletedAt: String, deadlineMs: Long,
): JSONObject = JSONObject()
        .put("schema_version", "2.0").put("request_id", UUID.randomUUID().toString()).put("job_id", jobId)
        .put("pad_device_id", context.padDeviceId).put("workstation_id", context.workstationId)
        .put("standard_revision_id", context.standardId).put("bundle_version", context.bundleVersion ?: "unknown")
        .put("capture_confirmed_at", captureAt)
        .put("client_deadline_at", Instant.now().plusMillis(deadlineMs).toString())
        .put("compression_profile_id", "configured")
        .put("points", JSONArray(crops.map { crop ->
            val point = points.first { it.qcPointCode == crop.pointCode }
            JSONObject().put("point_code", crop.pointCode).put("crop_id", crop.cropId)
                .put("crop_part", "${crop.cropId}.jpg").put("crop_sha256", crop.sha256)
                .put("encoded_bytes", crop.bytes.size).put("width_px", crop.widthPx).put("height_px", crop.heightPx)
                .put("region_in_capture", JSONObject().put("x", crop.region.x).put("y", crop.region.y).put("w", crop.region.w).put("h", crop.region.h))
                .put("severity", point.ruleType ?: "major").put("expected_value", point.expectedValue ?: JSONObject.NULL)
                .put("pass_criteria", point.passCriteria ?: point.description)
                .apply {
                    // With no authored config these two fields remain exactly
                    // the pre-WS8 wire values. A configured analyzer failure is
                    // evidence, never a reason to suppress the cloud VLM call.
                    if (point.cvConfigJson == null) {
                        put("cv_status", "not_configured").put("cv_analysis", JSONObject.NULL)
                    } else {
                        put("cv_config", JSONObject(point.cvConfigJson))
                        point.expectedFeaturesJson?.let { put("expected_features", JSONObject(it)) }
                        val analysis = point.cvAnalysisJson?.let { JSONObject(it) }
                        put("cv_status", point.cvStatus ?: if (analysis == null) "failed" else "completed")
                        put("cv_analysis", analysis ?: JSONObject.NULL)
                    }
                }
        }))
        .put("client_timing", JSONObject().put("capture_confirmed_at", captureAt)
            .put("cv_started_at", cvStartedAt).put("cv_completed_at", cvCompletedAt)
            .put("per_crop", JSONArray()))
