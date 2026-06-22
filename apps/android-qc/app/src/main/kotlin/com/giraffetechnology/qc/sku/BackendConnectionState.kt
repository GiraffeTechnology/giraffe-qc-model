package com.giraffetechnology.qc.sku

sealed class BackendConnectionState {
    object Unknown : BackendConnectionState()
    object Connected : BackendConnectionState()
    object Offline : BackendConnectionState()
    data class Error(val message: String) : BackendConnectionState()
}
