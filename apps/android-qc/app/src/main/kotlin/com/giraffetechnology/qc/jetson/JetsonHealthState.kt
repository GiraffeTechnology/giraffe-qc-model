package com.giraffetechnology.qc.jetson

/**
 * Mirrors `src/qc_model/jetson/constants.py`'s readiness enum exactly -- same
 * wire strings as the Jetson and Server, per
 * `docs/api-contracts/jetson-runner-api.md` §3 /
 * `docs/api-contracts/pad-jetson-health-state.md` §2.
 */
enum class JetsonReadinessState(val wireValue: String) {
    READY("jetson_ready"),
    CONNECTING("jetson_connecting"),
    UNREACHABLE("jetson_unreachable"),
    NO_STANDARD_INSTALLED("no_standard_installed"),
    NO_SKU_SELECTED("no_sku_selected");

    val canSubmitInspection: Boolean get() = this == READY

    companion object {
        fun fromWire(value: String?): JetsonReadinessState =
            entries.firstOrNull { it.wireValue == value } ?: UNREACHABLE
    }
}

/** Raw poll of the Jetson's `GET /health` (jetson-runner-api.md §1.1). */
data class JetsonHealthSnapshot(
    val serviceUp: Boolean,
    val modelLoaded: Boolean,
    val temperatureC: Double?,
    val throttling: Boolean?,
    val diskFreePercent: Double?,
    val lastInferenceLatencyMs: Int?,
    val readinessState: JetsonReadinessState,
    val jetsonDeviceId: String,
    val agentVersion: String,
    val adapterName: String?,
    val modelName: String?,
    val polledAtEpochMs: Long,
    /**
     * True if this snapshot came from `JETSON_MOCK_MODE=true` -- must be
     * surfaced in the UI per the mock-labeling ground rule, never silently
     * hidden. Absent/missing on an old runner is treated as unknown-not-mock
     * (`false`) rather than assumed mock, since a missing field on a real
     * deployment is the more likely case once WS5 ships.
     */
    val isMock: Boolean,
)

sealed class PairingState {
    object Unpaired : PairingState()
    data class Pairing(val path: String) : PairingState()
    data class Paired(val jetsonDeviceId: String, val pairingPath: String, val host: String, val port: Int) : PairingState()
}

/** What the Operator work screen and the health display both bind to. */
data class PadJetsonState(
    val pairing: PairingState = PairingState.Unpaired,
    val lastHealth: JetsonHealthSnapshot? = null,
    val readiness: JetsonReadinessState = JetsonReadinessState.UNREACHABLE,
) {
    val canSubmitInspection: Boolean get() = readiness.canSubmitInspection
}
