package com.giraffetechnology.qc.operator.cloud

import com.giraffetechnology.qc.admin.CloudLinkHealth
import com.giraffetechnology.qc.admin.NanoCvHealth
import com.giraffetechnology.qc.admin.OfflineQueueHealth
import com.giraffetechnology.qc.admin.PadHealthState
import com.giraffetechnology.qc.admin.PadHealthStateSource
import com.giraffetechnology.qc.admin.XavierAdminHealth
import java.time.Instant
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class OperatorPadHealthStateSource(
    private val monitor: CloudRuntimeMonitor,
    private val queue: CloudPendingJobStore,
) : PadHealthStateSource {
    private val _state = MutableStateFlow(snapshot())
    override val state: StateFlow<PadHealthState> = _state.asStateFlow()

    override suspend fun refresh() {
        monitor.refresh()
        _state.value = snapshot()
    }

    private fun snapshot(): PadHealthState {
        val decision = monitor.lastDecision
        val ready = monitor.cloudReachable && decision.selected != OperatorNetwork.NONE
        return PadHealthState(
            observedAt = Instant.now().toString(), padDeviceId = monitor.padDeviceId,
            operatorPipelineReadiness = when {
                ready -> "ready"
                queue.pendingCount() > 0 -> "degraded_queue_available"
                decision.selected == OperatorNetwork.NONE -> "offline"
                else -> "cloud_unreachable"
            },
            canStartJob = ready,
            // WS8/Nano agent has not yet supplied a heartbeat. Cropping exists,
            // but claiming a Nano CV agent is ready would be inaccurate.
            nanoCv = NanoCvHealth(status = "unknown"),
            cloudLink = CloudLinkHealth(
                state = if (ready) "healthy" else if (decision.selected == OperatorNetwork.NONE) "offline" else "degraded",
                cloudService = if (monitor.cloudReachable) "reachable" else "unreachable",
                acceptingJobs = monitor.cloudReachable,
                currentNetwork = decision.selected.wire,
                activeJobNetwork = monitor.networkPolicy.activeJobNetwork()?.wire,
                switchDeferredUntilJobEnd = monitor.networkPolicy.switchDeferredUntilJobEnd(),
                thresholdBreaches = decision.breaches,
            ),
            offlineQueue = OfflineQueueHealth(
                pendingUploadJobs = queue.pendingCount(), oldestPendingSince = queue.oldestPendingSince(),
            ),
            xavierAdmin = XavierAdminHealth(status = "not_configured"),
            limitations = listOf(
                "TODO(backend-pending): WS8 Nano CV heartbeat is not connected; status remains unknown.",
                "TODO(backend-pending): Administrator Xavier endpoint provisioning is not configured on this Pad.",
            ),
        )
    }
}
