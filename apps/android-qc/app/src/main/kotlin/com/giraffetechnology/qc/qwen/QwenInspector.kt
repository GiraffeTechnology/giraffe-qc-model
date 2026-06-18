package com.giraffetechnology.qc.qwen

// ── Input / context types ────────────────────────────────────────────────────

data class StandardPhotoInput(
    val photoId: String,
    val localPath: String,
    val angle: String? = null,
)

data class CapturePhotoInput(
    val photoId: String,
    val localPath: String,
)

data class QcPointInput(
    val qcPointId: String,
    val qcPointCode: String,
    val name: String,
    val description: String,
    val roiJson: String? = null,
    val ruleType: String? = null,
)

data class InspectionContext(
    val tenantId: String,
    val skuId: String,
    val standardId: String,
    val inspectionId: String,
)

// ── Output types (§4.3.4 schema) ─────────────────────────────────────────────

data class InspectionItemResult(
    val qcPointId: String,
    val qcPointCode: String,
    val name: String,
    val result: String,       // "pass" | "fail" | "review_required"
    val confidence: Float,
    val reason: String,
    val evidence: Map<String, Any> = emptyMap(),
)

data class FallbackInfo(
    val used: Boolean = false,
    val reason: String? = null,
)

data class QwenInspectionOutput(
    val overallResult: String,  // "pass" | "fail" | "review_required"
    val engine: String,         // "local_qwen_mnn" | "cloud_qwen"
    val modelName: String,
    val confidence: Float,
    val items: List<InspectionItemResult>,
    val fallback: FallbackInfo,
    val summary: String = "",
) {
    fun copy(
        overallResult: String = this.overallResult,
        engine: String = this.engine,
        modelName: String = this.modelName,
        confidence: Float = this.confidence,
        items: List<InspectionItemResult> = this.items,
        fallback: FallbackInfo = this.fallback,
        summary: String = this.summary,
    ) = QwenInspectionOutput(overallResult, engine, modelName, confidence, items, fallback, summary)
}

// ── Inspector interface (§4.3.3) ──────────────────────────────────────────────

interface QwenInspector {
    val engineName: String
    val modelName: String

    suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput
}
