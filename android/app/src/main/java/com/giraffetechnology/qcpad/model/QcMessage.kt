package com.giraffetechnology.qcpad.model

/**
 * Typed boundary for messages pushed from giraffe-qc-model backend.
 * Wire format (JSON schema) is TBD per spec; update parseMessage() in
 * QcWebSocketClient when the schema is finalised — no UI code changes needed.
 */
sealed class QcMessage {
    data class DetectionResult(
        val skuId: String,
        val passed: Boolean,
        val referenceImageUrl: String? = null
    ) : QcMessage()

    data object ConnectionLost : QcMessage()
    data object ConnectionRestored : QcMessage()
}

enum class AggregateStatus { PASS, FAIL, UNKNOWN }
