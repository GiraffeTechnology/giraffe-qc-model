package com.giraffetechnology.qc.admin

import java.time.Instant
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Architecture v2 Pad health boundary from docs/api-contracts/pad-health-state.md. */
data class NanoCvHealth(
    val status: String,
    val agentVersion: String? = null,
    val pipelineVersion: String? = null,
    val lastSuccessAt: String? = null,
    val lastErrorCode: String? = null,
    val lastCvDurationMs: Long? = null,
)

data class NetworkThresholds(
    val minUplinkMbps: Double = 4.0,
    val maxRttMs: Long = 300,
    val maxPacketLossPercent: Double = 5.0,
    val wifiReturnMinUplinkMbps: Double = 6.0,
    val wifiReturnSustainSeconds: Long = 60,
)

data class CloudLinkHealth(
    val state: String,
    val cloudService: String,
    val acceptingJobs: Boolean,
    val currentNetwork: String,
    val activeJobNetwork: String? = null,
    val switchDeferredUntilJobEnd: Boolean = false,
    val effectiveUplinkMbps: Double? = null,
    val rttMs: Long? = null,
    val packetLossPercent: Double? = null,
    val sampleWindowSize: Int = 0,
    val thresholds: NetworkThresholds = NetworkThresholds(),
    val thresholdBreaches: List<String> = emptyList(),
    val wifiReturnEligibleAt: String? = null,
    val lastProbeAt: String? = null,
    val lastRealTransferAt: String? = null,
    val lastSwitchSummary: String? = null,
)

data class OfflineQueueHealth(
    val pendingUploadJobs: Int? = null,
    val oldestPendingSince: String? = null,
    val lastRetryAt: String? = null,
    val lastErrorCode: String? = null,
)

data class XavierAdminHealth(
    val status: String,
    val runnerId: String? = null,
    val runtimeEngine: String? = null,
    val adapterMode: String? = null,
    val modelName: String? = null,
    val modelLoaded: Boolean? = null,
    val temperatureC: Double? = null,
    val thermalState: String = "unknown",
    val diskFreeBytes: Long? = null,
    val lastRecognitionLatencyMs: Long? = null,
    val lastSeenAt: String? = null,
    val mock: Boolean = false,
    val hardwareValidationStatus: String = "not_run",
)

data class PadHealthState(
    val schemaVersion: String = "2.0",
    val observedAt: String,
    val padDeviceId: String = "",
    val workstationId: String? = null,
    val operatorPipelineReadiness: String,
    val canStartJob: Boolean,
    val nanoCv: NanoCvHealth,
    val cloudLink: CloudLinkHealth,
    val offlineQueue: OfflineQueueHealth,
    val xavierAdmin: XavierAdminHealth,
    /** Explicit missing-dependency notes; never converted into healthy values. */
    val limitations: List<String> = emptyList(),
)

interface PadHealthStateSource {
    val state: StateFlow<PadHealthState>
    suspend fun refresh()
}

/**
 * Contract-correct source used until WS4 supplies the Nano/cloud aggregator and
 * the signed Xavier client is provisioned. Only the dependency call is pending;
 * the UI/state shape is real. Unknown numeric facts remain null, never zeroed.
 */
class BackendPendingPadHealthStateSource : PadHealthStateSource {
    private val _state = MutableStateFlow(pendingSnapshot())
    override val state: StateFlow<PadHealthState> = _state.asStateFlow()

    override suspend fun refresh() {
        _state.value = pendingSnapshot()
    }

    private companion object {
        fun pendingSnapshot() = PadHealthState(
            observedAt = Instant.now().toString(),
            operatorPipelineReadiness = "unknown",
            canStartJob = false,
            nanoCv = NanoCvHealth(status = "unknown"),
            cloudLink = CloudLinkHealth(
                state = "unknown",
                cloudService = "unknown",
                acceptingJobs = false,
                currentNetwork = "unknown",
            ),
            offlineQueue = OfflineQueueHealth(),
            xavierAdmin = XavierAdminHealth(status = "not_configured"),
            limitations = listOf(
                "TODO(backend-pending): WS4 PadHealthState producer is not wired; " +
                    "Nano/cloud observations remain unknown.",
                "TODO(backend-pending): signed Xavier health provisioning is not wired; " +
                    "Administrator Xavier remains not_configured.",
            ),
        )
    }
}

data class AdminHealthState(
    val snapshot: PadHealthState,
    val refreshing: Boolean = false,
    val error: String? = null,
)

/** WS3 consumes one immutable state source and never polls subsystems itself. */
class AdminHealthController(private val source: PadHealthStateSource) {
    private val _state = MutableStateFlow(AdminHealthState(source.state.value))
    val state: StateFlow<AdminHealthState> = _state.asStateFlow()

    suspend fun refresh() {
        _state.value = _state.value.copy(refreshing = true, error = null)
        runCatching { source.refresh() }
            .onSuccess { _state.value = AdminHealthState(source.state.value) }
            .onFailure { error ->
                _state.value = _state.value.copy(
                    refreshing = false,
                    error = error.message ?: "health refresh failed",
                )
            }
    }
}
