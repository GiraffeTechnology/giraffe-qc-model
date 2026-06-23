package com.giraffetechnology.qc.multimodal

import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.StandardPhotoInput

/**
 * Provider-neutral QC inspector interface.
 *
 * Implementations: LocalMnnInspector (on-device MNN via MnnQwenInspector),
 * BackendProxyInspector (HTTP to server), MockInspector (CI/tests).
 *
 * Output type intentionally reuses QwenInspectionOutput so MultimodalInspectionRouter
 * can replace QwenInspectionRouter without requiring callers to migrate output types.
 * All result strings in the output are locked to SharedQcContract.VALID_RESULTS.
 */
interface MultimodalInspector {
    val inspectorName: String
    val modelName: String
    val contractVersion: String get() = SharedQcContract.QC_CONTRACT_VERSION

    suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput
}
