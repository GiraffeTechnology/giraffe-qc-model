package com.giraffetechnology.qc.multimodal

import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.MnnQwenInspector
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.StandardPhotoInput

/**
 * Provider-neutral adapter wrapping MnnQwenInspector.
 *
 * Delegates every call to the underlying MnnQwenInspector without adding logic.
 * This adapter exists so MultimodalInspectionRouter can name the on-device provider
 * without coupling to Qwen-specific class names at the router boundary.
 *
 * MnnQwenInspector already enforces the fail-closed policy (native error → review_required).
 * No duplicate policy logic is added here.
 */
class LocalMnnInspector(
    private val mnnInspector: MnnQwenInspector,
) : MultimodalInspector {

    override val inspectorName: String = "local_mnn"
    override val modelName: String get() = mnnInspector.modelName

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = mnnInspector.inspect(standardPhotos, capturedPhoto, qcPoints, context)
}
