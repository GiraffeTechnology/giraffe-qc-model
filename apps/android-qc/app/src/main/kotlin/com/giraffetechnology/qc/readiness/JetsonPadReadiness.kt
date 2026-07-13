package com.giraffetechnology.qc.readiness

import com.giraffetechnology.qc.sku.MnnRuntimeState

/**
 * Jetson-flavored counterpart to [PadReadiness] -- same evaluation shape and
 * fail-closed rule (PR30: "Model ready" only when [PadReadinessInputs.inferenceVerified]
 * is true), but with wording that describes a LAN-connected Jetson Xavier NX
 * rather than an on-device MNN runtime, per WS4's requirement to replace the
 * MNN-era readiness states rather than mislabel Jetson state with MNN text.
 *
 * The two "Jetson connecting" / "Jetson unreachable — offline mode" strings
 * are copied verbatim from `src/qc_model/jetson/constants.py`'s
 * `READINESS_LABELS` so Pad and Server terminology stay identical (see
 * `docs/jetson-runtime-readiness.md`).
 */
object JetsonPadReadiness {

    const val KEY_JETSON_CONNECTING = "readiness.jetson_connecting"
    const val KEY_JETSON_UNREACHABLE = "readiness.jetson_unreachable"

    fun evaluate(inputs: PadReadinessInputs): PadReadinessView {
        val runtimeKey = when {
            !inputs.mnnNativeReady -> KEY_JETSON_UNREACHABLE
            inputs.modelLoaded && inputs.inferenceVerified -> PadReadiness.KEY_MODEL_READY
            else -> KEY_JETSON_CONNECTING
        }
        val connectivityKey = if (inputs.online) PadReadiness.KEY_ONLINE else PadReadiness.KEY_OFFLINE

        val messageKeys = buildList {
            add(runtimeKey)
            if (!inputs.skuSelected) add(PadReadiness.KEY_NO_SKU_SELECTED)
            if (!inputs.standardInstalled) add(PadReadiness.KEY_NO_STANDARD_INSTALLED)
            add(connectivityKey)
        }

        return PadReadinessView(
            runtimeKey = runtimeKey,
            connectivityKey = connectivityKey,
            messageKeys = messageKeys,
            canClaimModelReady = runtimeKey == PadReadiness.KEY_MODEL_READY,
        )
    }

    /**
     * Convenience mapping from [JetsonRuntimeMonitor][com.giraffetechnology.qc.jetson.JetsonRuntimeMonitor]'s
     * [MnnRuntimeState] flow (see that class for the exact state mapping from
     * Jetson pairing/health):
     * - NotReady → not paired or Jetson unreachable → "Jetson unreachable — offline mode".
     * - Loading  → paired and reachable, service/model still coming up → "Jetson connecting…".
     * - Ready    → paired, reachable, service up, model loaded; whether it may
     *   claim "Model ready" still depends on [inferenceVerified] (fail-closed, PR30).
     */
    fun fromRuntimeState(
        state: MnnRuntimeState,
        inferenceVerified: Boolean,
        standardInstalled: Boolean,
        skuSelected: Boolean,
        online: Boolean,
    ): PadReadinessView = evaluate(
        PadReadinessInputs(
            mnnNativeReady = state !is MnnRuntimeState.NotReady,
            modelLoaded = state is MnnRuntimeState.Ready,
            inferenceVerified = inferenceVerified,
            standardInstalled = standardInstalled,
            skuSelected = skuSelected,
            online = online,
        ),
    )
}
