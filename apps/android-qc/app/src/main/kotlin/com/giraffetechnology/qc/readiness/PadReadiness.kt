package com.giraffetechnology.qc.readiness

import com.giraffetechnology.qc.sku.MnnRuntimeState

/**
 * Runtime-readiness resolver for the QC Work page (S6 §8.3).
 *
 * Produces the **exact** readiness states, as i18n keys, and never overclaims.
 * The fail-closed rule ties to PR30: the top production-ready state
 * ("Model ready") is only reachable when on-device inference is actually
 * hardware-verified ([PadReadinessInputs.inferenceVerified], sourced from
 * `MnnRuntimeLoader.JNI_INFERENCE_WIRED`). While that is false, the best the Pad
 * will claim is "MNN native ready; model pending", even if the model weights
 * loaded — so the UI can never assert full production readiness the native path
 * hasn't earned.
 *
 * Pure logic (no Android types) so it is unit-tested on the JVM.
 */
object PadReadiness {

    // Exact i18n keys → exact English strings live in PadLanguageCatalog.
    const val KEY_MODEL_READY = "readiness.model_ready"
    const val KEY_MNN_NATIVE_READY_MODEL_PENDING = "readiness.mnn_native_ready_model_pending"
    const val KEY_LOCAL_RUNTIME_NOT_READY = "readiness.local_runtime_not_ready"
    const val KEY_NO_STANDARD_INSTALLED = "readiness.no_standard_installed"
    const val KEY_NO_SKU_SELECTED = "readiness.no_sku_selected"
    const val KEY_OFFLINE = "readiness.offline"
    const val KEY_ONLINE = "readiness.online"

    fun evaluate(inputs: PadReadinessInputs): PadReadinessView {
        val runtimeKey = when {
            !inputs.mnnNativeReady -> KEY_LOCAL_RUNTIME_NOT_READY
            inputs.modelLoaded && inputs.inferenceVerified -> KEY_MODEL_READY
            else -> KEY_MNN_NATIVE_READY_MODEL_PENDING
        }
        val connectivityKey = if (inputs.online) KEY_ONLINE else KEY_OFFLINE

        val messageKeys = buildList {
            add(runtimeKey)
            if (!inputs.skuSelected) add(KEY_NO_SKU_SELECTED)
            if (!inputs.standardInstalled) add(KEY_NO_STANDARD_INSTALLED)
            add(connectivityKey)
        }

        return PadReadinessView(
            runtimeKey = runtimeKey,
            connectivityKey = connectivityKey,
            messageKeys = messageKeys,
            // Only a verified, model-loaded runtime may claim production readiness.
            canClaimModelReady = runtimeKey == KEY_MODEL_READY,
        )
    }

    /**
     * Convenience mapping from the live [MnnRuntimeState] flow:
     * - NotReady → native runtime not confirmed → "Local runtime not ready".
     * - Loading  → native libs engaged, model still loading → "…model pending".
     * - Ready    → model loaded; whether it may claim "Model ready" still depends
     *   on [inferenceVerified] (fail-closed per PR30).
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
        )
    )
}

data class PadReadinessInputs(
    /** MNN native libraries are loaded/available. */
    val mnnNativeReady: Boolean,
    /** Model weights are loaded into the native runtime (runtime reports Ready). */
    val modelLoaded: Boolean,
    /** On-device inference is hardware-verified (PR30 JNI_INFERENCE_WIRED). */
    val inferenceVerified: Boolean,
    val standardInstalled: Boolean,
    val skuSelected: Boolean,
    val online: Boolean,
)

data class PadReadinessView(
    val runtimeKey: String,
    val connectivityKey: String,
    /** Ordered readiness lines to show (runtime, selection gaps, connectivity). */
    val messageKeys: List<String>,
    /** True only when the Pad may honestly claim full production readiness. */
    val canClaimModelReady: Boolean,
)
