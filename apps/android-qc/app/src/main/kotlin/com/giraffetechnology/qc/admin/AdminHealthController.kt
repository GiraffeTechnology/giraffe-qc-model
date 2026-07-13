package com.giraffetechnology.qc.admin

import com.giraffetechnology.qc.sku.MnnRuntimeState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Pad-side facts the health screen renders — all real, gathered on refresh. */
data class PadHealthSnapshot(
    val modelState: String,
    val diskFreeBytes: Long,
    val diskTotalBytes: Long,
    val appVersionName: String,
    /** WS1 build provenance (commit SHA etc.) once merged; version until then. */
    val buildProvenance: String,
)

/** Injectable providers so the controller is unit-testable off-device. */
interface PadHealthProbe {
    fun diskFreeBytes(): Long
    fun diskTotalBytes(): Long
    fun appVersionName(): String
    fun buildProvenance(): String
}

sealed class JetsonHealthState {
    /**
     * The Jetson NX health API contract (WS4/WS5) is not yet published to
     * docs/api-contracts/ — the panel states this instead of showing data.
     */
    data class BackendPending(val reason: String) : JetsonHealthState()
    data class Error(val message: String) : JetsonHealthState()
    data class Loaded(val summary: String) : JetsonHealthState()
}

data class AdminHealthState(
    val pad: PadHealthSnapshot?,
    val jetson: JetsonHealthState,
)

/**
 * Pad/Jetson health view (WS3 item 8). Pad-side health is real (MNN runtime
 * state, disk, app build); the Jetson panel is wired to [AdminApiClient.fetchJetsonHealth],
 * which is backend-pending and says so.
 */
class AdminHealthController(
    private val client: AdminApiClient,
    private val probe: PadHealthProbe,
    private val runtimeState: StateFlow<MnnRuntimeState>,
) {
    private val _state = MutableStateFlow(
        AdminHealthState(pad = null, jetson = JetsonHealthState.BackendPending("not fetched"))
    )
    val state: StateFlow<AdminHealthState> = _state.asStateFlow()

    fun refresh() {
        val pad = PadHealthSnapshot(
            modelState = when (runtimeState.value) {
                is MnnRuntimeState.Ready -> "ready"
                is MnnRuntimeState.Loading -> "loading"
                is MnnRuntimeState.NotReady -> "not_ready"
            },
            diskFreeBytes = probe.diskFreeBytes(),
            diskTotalBytes = probe.diskTotalBytes(),
            appVersionName = probe.appVersionName(),
            buildProvenance = probe.buildProvenance(),
        )
        val jetson = when (val r = client.fetchJetsonHealth()) {
            is AdminApiResult.Ok -> JetsonHealthState.Loaded("ok")
            is AdminApiResult.Error ->
                if (r.message.startsWith("backend-pending")) {
                    JetsonHealthState.BackendPending(r.message)
                } else {
                    JetsonHealthState.Error(r.message)
                }
        }
        _state.value = AdminHealthState(pad = pad, jetson = jetson)
    }
}
