package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.StateFlow

interface SkuMatcher {
    val runtimeState: StateFlow<MnnRuntimeState>
    suspend fun match(capturedImagePath: String): SkuMatchResult
}
