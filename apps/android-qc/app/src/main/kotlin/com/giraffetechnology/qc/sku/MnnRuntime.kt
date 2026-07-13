package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.StateFlow

/**
 * Read-only view of a local-or-LAN inference runtime's readiness.
 *
 * Lets PadInspectionCoordinator observe runtime state without depending on a
 * concrete implementation (MnnRuntimeLoader requires an Android Context; a
 * Jetson-backed runtime needs LAN I/O), so JVM unit tests can drive readiness
 * with a plain fake. Despite the historical "Mnn"-prefixed name, this seam is
 * implementation-agnostic: MnnRuntimeLoader (on-device JNI, legacy/gated) and
 * JetsonRuntimeMonitor (default, LAN-backed) both implement it.
 */
interface MnnRuntime {
    val runtimeState: StateFlow<MnnRuntimeState>

    /**
     * Whether real inference has actually been hardware/network-verified for
     * this runtime (fail-closed gate, PR30) -- not just "a model claims to be
     * loaded". MnnRuntimeLoader ties this to [com.giraffetechnology.qc.qwen.MnnRuntimeLoader.JNI_INFERENCE_WIRED]
     * (always false -- on-device JNI has never been wired). JetsonRuntimeMonitor
     * ties this to an analogous tripwire that must only flip true once Phase 1.5
     * device validation confirms a real Pad-Jetson round trip works. Defaults to
     * false so an implementation that doesn't override this can never
     * accidentally claim verified readiness.
     */
    val inferenceVerified: Boolean get() = false
}
