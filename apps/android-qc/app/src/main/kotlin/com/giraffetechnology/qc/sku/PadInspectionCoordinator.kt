package com.giraffetechnology.qc.sku

import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.qwen.QwenInspector

/**
 * Coordinates a local pad-side QC inspection attempt.
 *
 * Rules:
 * - cloudInferenceUsed is always false.
 * - If MNN is not loaded, result is MNN_PENDING.
 * - If local inspection throws, result is review_required.
 * - ACCEPTED is only returned when the local model produces a parseable high-confidence pass.
 */
class PadInspectionCoordinator(
    private val qwenInspector: QwenInspector,
    private val runtimeLoader: MnnRuntimeLoader,
) {
    companion object {
        private const val MODEL_NAME = "Qwen3-VL-2B-Instruct-MNN"
    }

    suspend fun inspect(task: QcTask, photo: CapturedPhoto): PadInspectionResult {
        if (runtimeLoader.runtimeState.value !is MnnRuntimeState.Ready) {
            return PadInspectionResult(
                overallResult     = "MNN_PENDING",
                reason            = "Local MNN runtime not ready — please review manually",
                modelName         = MODEL_NAME,
                localOnly         = true,
                cloudInferenceUsed = false,
                capturedImagePath = photo.rawImagePath,
            )
        }
        return runCatching {
            val output = qwenInspector.inspect(
                standardPhotos = emptyList(),
                capturedPhoto  = CapturePhotoInput(
                    photoId   = photo.captureId,
                    localPath = photo.rawImagePath,
                ),
                qcPoints = emptyList(),
                context  = InspectionContext(
                    tenantId     = "pad",
                    skuId        = task.sku.id,
                    standardId   = task.sku.id,
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
