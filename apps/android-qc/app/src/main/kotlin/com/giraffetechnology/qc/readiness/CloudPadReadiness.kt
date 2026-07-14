package com.giraffetechnology.qc.readiness

import com.giraffetechnology.qc.sku.MnnRuntimeState

object CloudPadReadiness {
    const val KEY_READY = "readiness.cloud_pipeline_ready"
    const val KEY_CONNECTING = "readiness.cloud_connecting"
    const val KEY_UNAVAILABLE = "readiness.cloud_unavailable"

    fun fromRuntimeState(
        state: MnnRuntimeState,
        standardInstalled: Boolean,
        skuSelected: Boolean,
    ): PadReadinessView {
        val runtimeKey = when (state) {
            is MnnRuntimeState.Ready -> KEY_READY
            is MnnRuntimeState.Loading -> KEY_CONNECTING
            is MnnRuntimeState.NotReady -> KEY_UNAVAILABLE
        }
        return PadReadinessView(
            runtimeKey = runtimeKey,
            connectivityKey = if (state is MnnRuntimeState.Ready) PadReadiness.KEY_ONLINE else PadReadiness.KEY_OFFLINE,
            messageKeys = buildList {
                add(runtimeKey)
                if (!skuSelected) add(PadReadiness.KEY_NO_SKU_SELECTED)
                if (!standardInstalled) add(PadReadiness.KEY_NO_STANDARD_INSTALLED)
            },
            canClaimModelReady = state is MnnRuntimeState.Ready,
        )
    }
}
