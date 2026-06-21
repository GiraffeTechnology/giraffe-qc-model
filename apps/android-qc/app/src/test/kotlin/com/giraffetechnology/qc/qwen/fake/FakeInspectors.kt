package com.giraffetechnology.qc.qwen.fake

import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.delay

// Deterministic fake inspectors for unit/CI tests.
// Never load the real MNN model or call real cloud APIs in tests.
// Model name reflects the Pad branch target: Qwen3-VL-2B-Instruct-MNN.

class FakeOnDeviceQwenInspector(
    private val resultOverride: String = "pass",
    private val confidence: Float = 0.95f,
) : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "Qwen3-VL-2B-Instruct-MNN"

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = QwenInspectionOutput(
        overallResult = resultOverride,
        engine        = engineName,
        modelName     = modelName,
        confidence    = confidence,
        items         = qcPoints.map { p ->
            InspectionItemResult(p.qcPointId, p.qcPointCode, p.name,
                resultOverride, confidence, "fake_result")
        },
        fallback = FallbackInfo(used = false),
        summary  = "Fake on-device result: $resultOverride",
    )
}

class FailingOnDeviceQwenInspector : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "Qwen3-VL-2B-Instruct-MNN"
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = throw RuntimeException("on_device_error: simulated failure")
}

class TimeoutOnDeviceQwenInspector(private val delayMs: Long = 15_000L) : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "Qwen3-VL-2B-Instruct-MNN"
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        delay(delayMs)
        throw RuntimeException("should have timed out")
    }
}

class InvalidJsonOnDeviceQwenInspector : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "Qwen3-VL-2B-Instruct-MNN"
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = QwenInspectionOutput(
        overallResult = "review_required",
        engine        = engineName,
        modelName     = modelName,
        confidence    = 0.0f,
        items         = emptyList(),
        fallback      = FallbackInfo(used = false, reason = "json_parse_failed"),
        summary       = "json_parse_failed",
    )
}

class NotProvisionedOnDeviceQwenInspector : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "Qwen3-VL-2B-Instruct-MNN"
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = throw UnsupportedOperationException("on_device_model_not_provisioned")
}
