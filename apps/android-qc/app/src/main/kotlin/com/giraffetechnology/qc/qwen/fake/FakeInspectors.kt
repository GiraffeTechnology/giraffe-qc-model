package com.giraffetechnology.qc.qwen.fake

import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.delay

// §4.9.3 — Deterministic fake inspectors for unit/CI tests.
// Never load the real MNN model or call real cloud APIs in tests.

class FakeOnDeviceQwenInspector(
    private val resultOverride: String = "pass",
    private val confidence: Float = 0.95f,
) : QwenInspector {
    override val engineName = "local_qwen_mnn"
    override val modelName  = "FakeQwenVL"

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

// Mirrors MnnQwenInspector stub-mode behaviour (MNN AAR absent).
// Core invariant: stub mode must return review_required, never pass (confidence must be 0.0f
// so QwenInspectionRouter.isAcceptable() rejects it regardless of minConfidence threshold).
class StubModeQwenInspector : QwenInspector {
    override val engineName = "local_qwen_mnn_stub"
    override val modelName  = "Qwen3-VL-4B-Instruct-MNN (STUB_MODE)"
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
        items         = qcPoints.map { p ->
            InspectionItemResult(p.qcPointId, p.qcPointCode, p.name,
                "review_required", 0.0f, "stub_mode_real_mnn_not_available")
        },
        fallback = FallbackInfo(used = false, reason = "stub_mode_real_mnn_not_available"),
        summary  = "stub_mode_real_mnn_not_available",
    )
}
