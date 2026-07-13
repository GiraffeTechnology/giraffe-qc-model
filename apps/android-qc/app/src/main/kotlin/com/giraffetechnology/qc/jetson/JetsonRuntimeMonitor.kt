package com.giraffetechnology.qc.jetson

import com.giraffetechnology.qc.sku.MnnRuntime
import com.giraffetechnology.qc.sku.MnnRuntimeState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Polls the paired Jetson's health over LAN and exposes both the rich
 * [PadJetsonState] (for the health display / readiness UI) and the
 * three-state [MnnRuntimeState] seam [PadInspectionCoordinator] already
 * knows how to gate on -- no changes needed there when swapping this in for
 * [com.giraffetechnology.qc.qwen.MnnRuntimeLoader].
 *
 * State mapping (Jetson readiness -> MnnRuntimeState, independent of
 * SKU/standard selection -- that's PadInspectionCoordinator's own
 * empty-standard gate, kept separate per the existing split):
 *   unpaired / unreachable  -> NotReady
 *   paired, reachable, but not (service_up && model_loaded) -> Loading
 *   paired, reachable, service_up && model_loaded -> Ready
 */
class JetsonRuntimeMonitor(
    private val pairingStore: JetsonPairingRepository,
    private val client: JetsonLanClient = JetsonLanClient(),
    private val pollIntervalMs: Long = 5000L,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
    /** Null = no relay (e.g. under test). See [JetsonServerRelay] for what this does and doesn't cover. */
    private val serverRelay: JetsonServerRelay? = null,
    private val tenantId: String = "default",
) : MnnRuntime {

    private val _runtimeState = MutableStateFlow<MnnRuntimeState>(MnnRuntimeState.NotReady)
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState.asStateFlow()

    // See MnnRuntime.inferenceVerified doc: a real Pad<->Jetson round trip has
    // never been hardware-verified (JetPack 5.1.x reflash + real adapter are
    // pending Phase 1.5 device-side work -- JETSON_NX_RUNTIME_FEASIBILITY.md).
    // Flip this ONLY in the same change that records that verification.
    override val inferenceVerified: Boolean get() = JETSON_INFERENCE_VERIFIED

    private val _jetsonState = MutableStateFlow(PadJetsonState())
    val jetsonState: StateFlow<PadJetsonState> = _jetsonState.asStateFlow()

    private var pollJob: Job? = null

    val baseUrl: String?
        get() = pairingStore.jetsonHost?.let { host -> "http://$host:${pairingStore.jetsonPort}" }

    /** Starts periodic health polling. Safe to call multiple times (idempotent). */
    fun start() {
        if (pollJob?.isActive == true) return
        refreshPairingState()
        pollJob = scope.launch {
            while (true) {
                pollOnce()
                delay(pollIntervalMs)
            }
        }
    }

    fun stop() {
        pollJob?.cancel()
        pollJob = null
    }

    suspend fun pollOnce() {
        refreshPairingState()
        val url = baseUrl
        if (url == null) {
            publish(PadJetsonState(pairing = PairingState.Unpaired, readiness = JetsonReadinessState.UNREACHABLE))
            return
        }
        val health = withContext(Dispatchers.IO) { client.health(url) }
        val paired = PairingState.Paired(
            jetsonDeviceId = pairingStore.jetsonDeviceId ?: "",
            pairingPath = pairingStore.pairingPath ?: "",
            host = pairingStore.jetsonHost ?: "",
            port = pairingStore.jetsonPort,
        )
        if (health == null) {
            publish(PadJetsonState(pairing = paired, lastHealth = null, readiness = JetsonReadinessState.UNREACHABLE))
            return
        }
        publish(PadJetsonState(pairing = paired, lastHealth = health, readiness = health.readinessState))
        // Best-effort fleet-visibility relay (docs/api-contracts/pad-jetson-health-state.md
        // §3) -- never blocks or affects the state just published above.
        serverRelay?.let { relay ->
            withContext(Dispatchers.IO) { runCatching { relay.relayHealth(tenantId, health) } }
        }
    }

    private fun refreshPairingState() {
        if (!pairingStore.isPaired && _jetsonState.value.pairing !is PairingState.Unpaired) {
            _jetsonState.value = PadJetsonState(pairing = PairingState.Unpaired, readiness = JetsonReadinessState.UNREACHABLE)
        }
    }

    private fun publish(state: PadJetsonState) {
        _jetsonState.value = state
        _runtimeState.value = when {
            state.pairing !is PairingState.Paired -> MnnRuntimeState.NotReady
            state.lastHealth == null -> MnnRuntimeState.NotReady
            !state.lastHealth.serviceUp -> MnnRuntimeState.NotReady
            state.lastHealth.serviceUp && state.lastHealth.modelLoaded -> MnnRuntimeState.Ready
            else -> MnnRuntimeState.Loading
        }
    }

    companion object {
        const val JETSON_INFERENCE_VERIFIED = false
    }
}
