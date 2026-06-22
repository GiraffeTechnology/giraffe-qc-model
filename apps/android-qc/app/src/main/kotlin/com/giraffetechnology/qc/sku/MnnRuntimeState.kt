package com.giraffetechnology.qc.sku

// Sealed class is intentionally in the sku package so TaskSelectionController
// and test fakes can use MnnRuntimeState.Ready / NotReady without additional imports.
sealed class MnnRuntimeState {
    object NotReady : MnnRuntimeState()
    object Loading  : MnnRuntimeState()
    object Ready    : MnnRuntimeState()
}
