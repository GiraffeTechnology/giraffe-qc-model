package com.giraffetechnology.qc.qwen.fake

import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.FallbackInfo
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.InspectionItemResult
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.QwenInspector
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.delay

// Test-only deterministic fake inspectors for unit/CI tests.
// These classes MUST NOT appear in src/main — use PendingTargetDetector there instead.

class FakeOnDeviceQwenInspector(
    private val resultOverride: String = "pass",
    private val confidence: Float = 0.95f,
) : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "FakeQwen-3B"

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
    override val modelName  = "FailingFake"
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = throw RuntimeException("on_device_error: simulated failure")
}

class TimeoutOnDeviceQwenInspector(private val delayMs: Long = 15_000L) : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "TimeoutFake"
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
    override val modelName  = "InvalidJsonFake"
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
    override val modelName  = "NotProvisionedFake"
    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput = throw UnsupportedOperationException("on_device_model_not_provisioned")
}
