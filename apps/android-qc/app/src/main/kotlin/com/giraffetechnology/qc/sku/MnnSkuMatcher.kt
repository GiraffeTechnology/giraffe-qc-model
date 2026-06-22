package com.giraffetechnology.qc.sku

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * On-device SKU visual matcher backed by Qwen3-VL-2B-Instruct-MNN.
 *
 * JNI wiring is scaffolded — match() returns REVIEW_REQUIRED until the
 * MNN AAR JNI path is integrated. Never returns a fake pass.
 */
class MnnSkuMatcher(
    @Suppress("UNUSED_PARAMETER") config: SkuMatchConfig = SkuMatchConfig(),
) : SkuMatcher {
    private val _runtimeState = MutableStateFlow<MnnRuntimeState>(MnnRuntimeState.NotReady)
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState.asStateFlow()

    override suspend fun match(capturedImagePath: String): SkuMatchResult {
        if (_runtimeState.value !is MnnRuntimeState.Ready) {
            return SkuMatchResult(
                status = MatchStatus.MNN_PENDING,
                candidates = emptyList(),
                capturedImagePath = capturedImagePath,
            )
        }
        // JNI call to MNN VL model scaffolded — wired at native integration time.
        // Never returns a fabricated pass or fail result.
        return SkuMatchResult(
            status = MatchStatus.REVIEW_REQUIRED,
            candidates = emptyList(),
            capturedImagePath = capturedImagePath,
        )
    }
}
