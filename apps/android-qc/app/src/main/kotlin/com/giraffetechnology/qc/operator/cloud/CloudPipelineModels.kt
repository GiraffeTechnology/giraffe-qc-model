package com.giraffetechnology.qc.operator.cloud

data class CompressionProfile(
    val id: String = "site-default",
    val maxCropBytes: Int,
    val maxLongestSidePx: Int,
    val jpegQuality: Int,
) {
    init {
        require(maxCropBytes in 1..HARD_MAX_CROP_BYTES)
        require(maxLongestSidePx > 0)
        require(jpegQuality in 1..100)
    }

    companion object { const val HARD_MAX_CROP_BYTES = 204_800 }
}

data class NormalizedRegion(val x: Double, val y: Double, val w: Double, val h: Double) {
    init {
        require(x >= 0 && y >= 0 && w > 0 && h > 0)
        require(x + w <= 1.0 && y + h <= 1.0)
        // A full frame is forbidden by the cloud contract.
        require(!(x == 0.0 && y == 0.0 && w == 1.0 && h == 1.0))
    }
}

data class EncodedCrop(
    val cropId: String,
    val pointCode: String,
    val bytes: ByteArray,
    val widthPx: Int,
    val heightPx: Int,
    val sha256: String,
    val region: NormalizedRegion,
)

data class CloudPointResult(
    val pointCode: String,
    val cropId: String,
    val result: String,
    val confidence: Float,
    val evidence: String,
    val cvStatus: String = "not_configured",
    val cvAnalysisJson: String? = null,
)

data class CloudTiming(
    val captureConfirmedAt: String,
    val cvStartedAt: String,
    val cvCompletedAt: String,
    val uploadStartedAt: String? = null,
    val uploadCompletedAt: String? = null,
    val responseReceivedAt: String? = null,
    val verdictRenderedAt: String? = null,
    val elapsedMs: Long? = null,
)

data class CloudRecognition(
    val jobId: String,
    val overallResult: String,
    val pointResults: List<CloudPointResult>,
    val providerAdapter: String,
    val modelFamily: String,
    val timing: CloudTiming,
)

enum class OperatorNetwork(val wire: String) { WIFI("wifi"), CELLULAR("cellular"), NONE("none") }

data class LinkSample(
    val network: OperatorNetwork,
    val uplinkMbps: Double?,
    val rttMs: Long?,
    val packetLossPercent: Double?,
    val observedAtMs: Long,
)

data class NetworkProbeResult(val uplinkMbps: Double, val rttMs: Long, val packetLossPercent: Double)

data class NetworkPolicyConfig(
    val minUplinkMbps: Double = 4.0,
    val sampleWindowSize: Int = 3,
    val maxRttMs: Long = 300,
    val maxPacketLossPercent: Double = 5.0,
    val wifiReturnMinUplinkMbps: Double = 6.0,
    val wifiReturnSustainMs: Long = 60_000,
)

data class NetworkDecision(
    val selected: OperatorNetwork,
    val breaches: List<String>,
    val switched: Boolean,
    val reason: String? = null,
)

data class PendingCloudJob(
    val jobId: String,
    val createdAt: String,
    val retryCount: Int,
    val nextRetryAt: String,
    val selectedNetwork: String,
    val lastErrorCode: String,
    val manifestJson: String,
    val cropPaths: List<String>,
)

sealed class CloudSubmitOutcome {
    data class Completed(val recognition: CloudRecognition) : CloudSubmitOutcome()
    data class Retryable(val code: String) : CloudSubmitOutcome()
    data class Rejected(val code: String) : CloudSubmitOutcome()
}
