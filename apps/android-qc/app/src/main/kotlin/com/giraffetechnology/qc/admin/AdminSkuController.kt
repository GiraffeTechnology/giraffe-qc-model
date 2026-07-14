package com.giraffetechnology.qc.admin

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class AdminSkuConfigState {
    object Loading : AdminSkuConfigState()
    data class Loaded(val lifecycleStates: List<String>) : AdminSkuConfigState()
    data class Error(val message: String) : AdminSkuConfigState()
}

sealed class AdminSkuListState {
    object Loading : AdminSkuListState()
    data class Loaded(val skus: List<AdminSkuSummary>) : AdminSkuListState()
    data class Error(val message: String) : AdminSkuListState()
}

sealed class AdminSkuCreateState {
    object Idle : AdminSkuCreateState()
    object Creating : AdminSkuCreateState()
    data class Created(val skuId: String) : AdminSkuCreateState()
    data class Error(val message: String) : AdminSkuCreateState()
}

/** SKU create / select (WS3 item 2) — structured form-based Phase-1 parity. */
class AdminSkuController(private val client: AdminApiClient) {

    private val _configState = MutableStateFlow<AdminSkuConfigState>(AdminSkuConfigState.Loading)
    val configState: StateFlow<AdminSkuConfigState> = _configState.asStateFlow()

    private val _listState = MutableStateFlow<AdminSkuListState>(AdminSkuListState.Loading)
    val listState: StateFlow<AdminSkuListState> = _listState.asStateFlow()

    private val _createState = MutableStateFlow<AdminSkuCreateState>(AdminSkuCreateState.Idle)
    val createState: StateFlow<AdminSkuCreateState> = _createState.asStateFlow()

    private val _selected = MutableStateFlow<AdminSkuSummary?>(null)
    val selected: StateFlow<AdminSkuSummary?> = _selected.asStateFlow()

    fun refresh(query: String = "", statusFilter: String = "") {
        if (_configState.value !is AdminSkuConfigState.Loaded) {
            _configState.value = when (val config = client.fetchSkuLifecycleStates()) {
                is AdminApiResult.Ok -> {
                    val states = config.value.filter { it.isNotBlank() }.distinct()
                    if (states.size == 7) AdminSkuConfigState.Loaded(states)
                    else AdminSkuConfigState.Error("backend returned an invalid SKU lifecycle")
                }
                is AdminApiResult.Error -> AdminSkuConfigState.Error(config.message)
            }
        }
        _listState.value = AdminSkuListState.Loading
        _listState.value = when (val r = client.listSkus(query, statusFilter)) {
            is AdminApiResult.Ok -> AdminSkuListState.Loaded(r.value)
            is AdminApiResult.Error -> AdminSkuListState.Error(r.message)
        }
    }

    fun create(itemNumber: String, name: String, category: String?, description: String?) {
        if (itemNumber.isBlank() || name.isBlank()) {
            _createState.value = AdminSkuCreateState.Error("item number and name are required")
            return
        }
        _createState.value = AdminSkuCreateState.Creating
        when (val r = client.createSku(itemNumber.trim(), name.trim(), category, description)) {
            is AdminApiResult.Ok -> {
                _createState.value = AdminSkuCreateState.Created(r.value)
                refresh()
                select(r.value)
            }
            is AdminApiResult.Error -> _createState.value = AdminSkuCreateState.Error(r.message)
        }
    }

    fun resetCreateState() {
        _createState.value = AdminSkuCreateState.Idle
    }

    fun select(skuId: String) {
        when (val r = client.getSku(skuId)) {
            is AdminApiResult.Ok -> _selected.value = r.value
            is AdminApiResult.Error -> _selected.value = null
        }
    }

    /** Re-fetch the selected SKU (after uploads / detection-point edits). */
    fun reloadSelected() {
        _selected.value?.let { select(it.id) }
    }
}
