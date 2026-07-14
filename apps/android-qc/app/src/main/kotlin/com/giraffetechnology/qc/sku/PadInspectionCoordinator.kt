package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.QwenInspector

/**
 * Coordinates the active Operator inspection engine. Architecture v2 defaults
 * to the signed cloud adapter; the same seam retains an explicit legacy mode.
 *
 * Rules:
 * - If cloud readiness is absent, there is no verdict and submission is blocked.
 * - Fail closed: if the task is missing standard photos or detection points,
 *   result is review_required — an inspection without a standard or without
 *   checkpoints can never be ACCEPTED.
 * - If local inspection throws, result is review_required.
 * - ACCEPTED is only returned when the local model produces a parseable pass
 *   over real standard photos and detection points.
 */
class PadInspectionCoordinator(
    private val qwenInspector: QwenInspector,
    private val runtime: MnnRuntime,
    private val padDeviceId: String = "unprovisioned",
    private val workstationId: String = "unassigned",
) {
    suspend fun inspect(task: QcTask, photo: CapturedPhoto): PadInspectionResult {
        val cloud = qwenInspector.engineName == "configured_cloud_vlm"
        if (runtime.runtimeState.value !is MnnRuntimeState.Ready) {
            return PadInspectionResult(
                overallResult     = if (cloud) "CLOUD_UNAVAILABLE" else "MNN_PENDING",
                reason            = if (cloud) "Cloud inference unavailable — no verdict available" else "Legacy MNN runtime not ready",
                modelName         = qwenInspector.modelName,
                localOnly         = !cloud,
                cloudInferenceUsed = cloud,
                capturedImagePath = photo.rawImagePath,
            )
        }

        // Fail closed: no standard to compare against, or no checkpoints to judge,
        // means there is nothing that can legitimately produce an ACCEPTED verdict.
        if (task.standardPhotos.isEmpty() || task.qcPoints.isEmpty()) {
            val missing = when {
                task.standardPhotos.isEmpty() && task.qcPoints.isEmpty() ->
                    "standard photos and detection points"
                task.standardPhotos.isEmpty() -> "standard photos"
                else                          -> "detection points"
            }
            return PadInspectionResult(
                overallResult     = "review_required",
                reason            = "Inspection inputs incomplete: missing $missing",
                modelName         = qwenInspector.modelName,
                localOnly         = !cloud,
                cloudInferenceUsed = cloud,
                capturedImagePath = photo.rawImagePath,
            )
        }

        return runCatching {
            val output = qwenInspector.inspect(
                standardPhotos = task.standardPhotos,
                capturedPhoto  = CapturePhotoInput(
                    photoId   = photo.captureId,
                    localPath = photo.rawImagePath,
                ),
                qcPoints = task.qcPoints,
                context  = InspectionContext(
                    tenantId     = task.tenantId,
                    skuId        = task.sku.id,
                    standardId   = task.activeStandardRevisionId ?: task.sku.id,
                    inspectionId = photo.captureId,
                    bundleVersion = task.bundleVersion,
                    workstationId = workstationId,
                    padDeviceId = padDeviceId,
                ),
            )
            PadInspectionResult(
                overallResult = when (output.overallResult.lowercase()) {
                    "pass" -> "ACCEPTED"
                    "fail" -> "NOT_ACCEPTED"
                    else   -> "review_required"
                },
                reason            = output.summary.ifEmpty { output.overallResult },
                modelName         = output.modelName,
                localOnly         = !cloud,
                cloudInferenceUsed = cloud,
                capturedImagePath = photo.rawImagePath,
                cloudJobId = output.cloudJobId,
                pointResultsJson = org.json.JSONArray(output.items.map { item ->
                    org.json.JSONObject().put("point_code", item.qcPointCode)
                        .put("result", item.result).put("confidence", item.confidence)
                        .put("reason", item.reason).put("evidence", org.json.JSONObject(item.evidence))
                }).toString(),
                timing = output.timing,
            )
        }.getOrElse { e ->
            val pending = e.message?.startsWith("pending_upload:") == true
            val jobId = if (pending) e.message?.split(':')?.getOrNull(1) else null
            PadInspectionResult(
                overallResult     = when { pending -> "PENDING_UPLOAD"; cloud -> "CLOUD_ERROR"; else -> "review_required" },
                reason            = when { pending -> "Pending upload — no verdict available"; cloud -> "Cloud inspection failed — no verdict available: ${e.message}"; else -> "Inspection error: ${e.message}" },
                modelName         = qwenInspector.modelName,
                localOnly         = !cloud,
                cloudInferenceUsed = cloud,
                capturedImagePath = photo.rawImagePath,
                cloudJobId = jobId,
            )
        }
    }
}
