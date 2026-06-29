package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.QwenInspector

/**
 * Coordinates a local pad-side QC inspection attempt.
 *
 * Rules:
 * - cloudInferenceUsed is always false.
 * - If MNN is not ready, result is MNN_PENDING.
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
) {
    companion object {
        private const val MODEL_NAME = "Qwen3-VL-2B-Instruct-MNN"
    }

    suspend fun inspect(task: QcTask, photo: CapturedPhoto): PadInspectionResult {
        if (runtime.runtimeState.value !is MnnRuntimeState.Ready) {
            return PadInspectionResult(
                overallResult     = "MNN_PENDING",
                reason            = "Local MNN runtime not ready — please review manually",
                modelName         = MODEL_NAME,
                localOnly         = true,
                cloudInferenceUsed = false,
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
                modelName         = MODEL_NAME,
                localOnly         = true,
                cloudInferenceUsed = false,
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
                localOnly         = true,
                cloudInferenceUsed = false,
                capturedImagePath = photo.rawImagePath,
            )
        }.getOrElse { e ->
            PadInspectionResult(
                overallResult     = "review_required",
                reason            = "Inspection error: ${e.message}",
                modelName         = MODEL_NAME,
                localOnly         = true,
                cloudInferenceUsed = false,
                capturedImagePath = photo.rawImagePath,
            )
        }
    }
}
