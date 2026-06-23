package com.giraffetechnology.qc.multimodal

import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.FallbackInfo
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.InspectionItemResult
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.StandardPhotoInput

/**
 * Deterministic mock inspector for CI tests and local development.
 * Never calls any API, never loads native libraries.
 * Result is normalised through SharedQcContract.normalizeResult() so tests
 * can safely pass arbitrary strings and assert the fail-closed behaviour.
 */
class MockInspector(
    private val resultOverride: String = SharedQcContract.RESULT_PASS,
    private val confidence: Float = 0.95f,
) : MultimodalInspector {

    override val inspectorName: String = "mock"
    override val modelName: String = "mock_multimodal_v1"

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        val result = SharedQcContract.normalizeResult(resultOverride)
        return QwenInspectionOutput(
            overallResult = result,
            engine        = inspectorName,
            modelName     = modelName,
            confidence    = confidence,
            items         = qcPoints.map { p ->
                InspectionItemResult(p.qcPointId, p.qcPointCode, p.name,
                    result, confidence, "mock_result")
            },
            fallback = FallbackInfo(used = false),
            summary  = "Mock result: $result",
        )
    }
}
