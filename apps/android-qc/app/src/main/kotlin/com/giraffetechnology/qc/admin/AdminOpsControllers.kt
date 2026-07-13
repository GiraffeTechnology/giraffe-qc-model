package com.giraffetechnology.qc.admin

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// ── Bundles (WS3 item 6) ─────────────────────────────────────────────────────

sealed class AdminBundleState {
    object Loading : AdminBundleState()
    data class Loaded(val bundles: List<AdminBundle>) : AdminBundleState()
    data class Error(val message: String) : AdminBundleState()
}

sealed class AdminPublishState {
    object Idle : AdminPublishState()
    object Publishing : AdminPublishState()
    data class Published(val bundleId: String) : AdminPublishState()
    data class Error(val message: String) : AdminPublishState()
}

class AdminBundleController(private val client: AdminApiClient) {

    private val _bundles = MutableStateFlow<AdminBundleState>(AdminBundleState.Loading)
    val bundles: StateFlow<AdminBundleState> = _bundles.asStateFlow()

    private val _publish = MutableStateFlow<AdminPublishState>(AdminPublishState.Idle)
    val publish: StateFlow<AdminPublishState> = _publish.asStateFlow()

    /** bundle id → verified manifest sha (proof the signed download verified). */
    private val _downloadChecks = MutableStateFlow<Map<String, String>>(emptyMap())
    val downloadChecks: StateFlow<Map<String, String>> = _downloadChecks.asStateFlow()

    fun refresh() {
        _bundles.value = AdminBundleState.Loading
        _bundles.value = when (val r = client.listBundles()) {
            is AdminApiResult.Ok -> AdminBundleState.Loaded(r.value)
            is AdminApiResult.Error -> AdminBundleState.Error(r.message)
        }
    }

    fun publish(skuId: String) {
        _publish.value = AdminPublishState.Publishing
        when (val r = client.publishBundle(skuId)) {
            is AdminApiResult.Ok -> {
                _publish.value = AdminPublishState.Published(r.value)
                refresh()
            }
            is AdminApiResult.Error -> _publish.value = AdminPublishState.Error(r.message)
        }
    }

    /** Server-verified signed download; records the verified manifest sha. */
    fun verifyDownload(bundlePk: String) {
        when (val r = client.downloadBundle(bundlePk)) {
            is AdminApiResult.Ok ->
                _downloadChecks.value = _downloadChecks.value + (bundlePk to r.value)
            is AdminApiResult.Error ->
                _downloadChecks.value = _downloadChecks.value + (bundlePk to "error: ${r.message}")
        }
    }

    fun resetPublishState() { _publish.value = AdminPublishState.Idle }
}

// ── Workstations (WS3 item 7) ────────────────────────────────────────────────

sealed class AdminWorkstationState {
    object Loading : AdminWorkstationState()
    data class Loaded(val workstations: List<AdminWorkstation>) : AdminWorkstationState()
    data class Error(val message: String) : AdminWorkstationState()
}

sealed class AdminWorkstationOpState {
    object Idle : AdminWorkstationOpState()
    object Working : AdminWorkstationOpState()
    data class Done(val workstation: AdminWorkstation) : AdminWorkstationOpState()
    data class Error(val message: String) : AdminWorkstationOpState()
}

class AdminWorkstationController(private val client: AdminApiClient) {

    private val _workstations =
        MutableStateFlow<AdminWorkstationState>(AdminWorkstationState.Loading)
    val workstations: StateFlow<AdminWorkstationState> = _workstations.asStateFlow()

    private val _opState = MutableStateFlow<AdminWorkstationOpState>(AdminWorkstationOpState.Idle)
    val opState: StateFlow<AdminWorkstationOpState> = _opState.asStateFlow()

    fun refresh() {
        _workstations.value = AdminWorkstationState.Loading
        _workstations.value = when (val r = client.listWorkstations()) {
            is AdminApiResult.Ok -> AdminWorkstationState.Loaded(r.value)
            is AdminApiResult.Error -> AdminWorkstationState.Error(r.message)
        }
    }

    fun register(workstationId: String, displayName: String, siteOrLine: String?) {
        if (workstationId.isBlank() || displayName.isBlank()) {
            _opState.value = AdminWorkstationOpState.Error("workstation id and name are required")
            return
        }
        _opState.value = AdminWorkstationOpState.Working
        when (val r = client.registerWorkstation(workstationId.trim(), displayName.trim(), siteOrLine)) {
            is AdminApiResult.Ok -> {
                _opState.value = AdminWorkstationOpState.Done(r.value)
                refresh()
            }
            is AdminApiResult.Error -> _opState.value = AdminWorkstationOpState.Error(r.message)
        }
    }

    fun assign(workstationPk: String, bundlePk: String) {
        _opState.value = AdminWorkstationOpState.Working
        when (val r = client.assignBundle(workstationPk, bundlePk)) {
            is AdminApiResult.Ok -> {
                _opState.value = AdminWorkstationOpState.Done(r.value)
                refresh()
            }
            is AdminApiResult.Error -> _opState.value = AdminWorkstationOpState.Error(r.message)
        }
    }

    fun resetOpState() { _opState.value = AdminWorkstationOpState.Idle }
}

// ── Results / incidents (WS3 item 10) ────────────────────────────────────────

sealed class AdminResultsState {
    object Loading : AdminResultsState()
    data class Loaded(
        val verdicts: List<AdminVerdict>,
        val suspensions: List<AdminSuspension>,
    ) : AdminResultsState()
    data class Error(val message: String) : AdminResultsState()
}

sealed class AdminDecisionState {
    object Idle : AdminDecisionState()
    object Saving : AdminDecisionState()
    data class Saved(val verdict: AdminVerdict) : AdminDecisionState()
    data class Error(val message: String) : AdminDecisionState()
}

class AdminResultsController(private val client: AdminApiClient) {

    private val _state = MutableStateFlow<AdminResultsState>(AdminResultsState.Loading)
    val state: StateFlow<AdminResultsState> = _state.asStateFlow()

    private val _decision = MutableStateFlow<AdminDecisionState>(AdminDecisionState.Idle)
    val decision: StateFlow<AdminDecisionState> = _decision.asStateFlow()

    fun refresh() {
        _state.value = AdminResultsState.Loading
        val verdicts = when (val r = client.listResults()) {
            is AdminApiResult.Ok -> r.value
            is AdminApiResult.Error -> {
                _state.value = AdminResultsState.Error(r.message)
                return
            }
        }
        // Suspension list failure must not hide the verdict list.
        val suspensions = when (val r = client.listSuspensions()) {
            is AdminApiResult.Ok -> r.value
            is AdminApiResult.Error -> emptyList()
        }
        _state.value = AdminResultsState.Loaded(verdicts, suspensions)
    }

    fun recordDecision(submissionId: String, decision: String, comment: String) {
        _decision.value = AdminDecisionState.Saving
        when (val r = client.recordFinalDecision(submissionId, decision, comment)) {
            is AdminApiResult.Ok -> {
                _decision.value = AdminDecisionState.Saved(r.value)
                refresh()
            }
            is AdminApiResult.Error -> _decision.value = AdminDecisionState.Error(r.message)
        }
    }

    fun resetDecisionState() { _decision.value = AdminDecisionState.Idle }
}

// ── Probation / qualification (WS3 item 9) ───────────────────────────────────

sealed class AdminProbationState {
    object Loading : AdminProbationState()
    /**
     * Suspensions come from the live `/api/qc/suspensions` API; the probation
     * gate/agreement panel awaits WS7's HTTP wiring and is explicitly marked
     * backend-pending in the UI ([probationBackendPending] carries the reason).
     */
    data class Loaded(
        val suspensions: List<AdminSuspension>,
        val probationBackendPending: String,
    ) : AdminProbationState()
    data class Error(val message: String) : AdminProbationState()
}

class AdminProbationController(private val client: AdminApiClient) {

    private val _state = MutableStateFlow<AdminProbationState>(AdminProbationState.Loading)
    val state: StateFlow<AdminProbationState> = _state.asStateFlow()

    fun refresh() {
        _state.value = AdminProbationState.Loading
        val suspensions = when (val r = client.listSuspensions()) {
            is AdminApiResult.Ok -> r.value
            is AdminApiResult.Error -> {
                _state.value = AdminProbationState.Error(r.message)
                return
            }
        }
        // TODO(backend-pending: docs/api-contracts/probation-service.md) —
        // probation gate/agreement/pause/resume wiring is WS7's; surface the
        // pending reason instead of pretending data exists.
        val pendingReason = when (val r = client.fetchProbation("")) {
            is AdminApiResult.Ok -> ""
            is AdminApiResult.Error -> r.message
        }
        _state.value = AdminProbationState.Loaded(suspensions, pendingReason)
    }
}
