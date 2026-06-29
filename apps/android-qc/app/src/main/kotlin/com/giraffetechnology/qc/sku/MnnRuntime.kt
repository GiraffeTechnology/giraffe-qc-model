package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.StateFlow

/**
 * Read-only view of the local MNN runtime readiness.
 *
 * Lets PadInspectionCoordinator observe runtime state without depending on the
 * concrete MnnRuntimeLoader (which requires an Android Context), so JVM unit
 * tests can drive readiness with a plain fake. MnnRuntimeLoader implements this.
 */
interface MnnRuntime {
    val runtimeState: StateFlow<MnnRuntimeState>
}
