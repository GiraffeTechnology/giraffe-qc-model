package com.giraffetechnology.qc.sku

import android.util.Log
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext

/**
 * MNN-backed SKU matcher.
 *
 * Uses the SAME MnnRuntimeLoader as QC inference — one shared runtime, two distinct call paths.
 * This path ONLY computes image similarity vs reference photos.
 * It NEVER calls nativeRunInference for QC and NEVER emits pass/fail.
 *
 * Functions called inside this class:
 *   - MnnRuntimeLoader.isLoaded()        — checks model handle is non-zero
 *   - MnnRuntimeLoader.modelPtr          — native handle (read-only)
 *   - nativeComputeSimilarity()          — placeholder; real JNI to be wired when available
 *
 * No Qwen3-VL inference, no cloud path, no DashScope.
 */
class MnnSkuMatcher(
    private val runtimeLoader: MnnRuntimeLoader,
    private val skuRepository: SkuRepository,
    private val config: SkuMatchConfig = SkuMatchConfig(),
) : SkuMatcher {

    companion object { private const val TAG = "MnnSkuMatcher" }

    private val _runtimeState = MutableStateFlow<MnnRuntimeState>(
        if (runtimeLoader.isLoaded()) MnnRuntimeState.Ready else MnnRuntimeState.NotReady
    )
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState.asStateFlow()

    fun syncRuntimeState() {
        _runtimeState.value = if (runtimeLoader.isLoaded()) MnnRuntimeState.Ready else MnnRuntimeState.NotReady
    }

    override suspend fun match(capturedImagePath: String): SkuMatchResult = withContext(Dispatchers.Default) {
        syncRuntimeState()

        if (!runtimeLoader.isLoaded()) {
            Log.w(TAG, "MNN not ready — status=MNN_PENDING, manual path still available")
            return@withContext SkuMatchResult(
                status             = MatchStatus.MNN_PENDING,
                candidates         = emptyList(),
                capturedImagePath  = capturedImagePath,
            )
        }

        val allSkus = runCatching { skuRepository.listAll(0, 200) }.getOrElse { emptyList() }

        val rawScores = allSkus.mapNotNull { sku ->
            sku.referencePhotoPaths.mapNotNull { refPath ->
                runCatching {
                    val sim = nativeComputeSimilarity(
                        runtimeLoader.modelPtr, capturedImagePath, refPath
                    )
                    SkuCandidate(sku, sim, refPath)
                }.getOrNull()
            }.maxByOrNull { it.similarity }
        }
        .sortedByDescending { it.similarity }
        .take(config.maxCandidates)

        if (rawScores.isEmpty()) {
            Log.i(TAG, "match: no candidates above threshold")
            return@withContext SkuMatchResult(MatchStatus.NO_MATCH, emptyList(), capturedImagePath)
        }

        val top1 = rawScores[0].similarity
        val top2 = rawScores.getOrNull(1)?.similarity ?: 0f
        val reviewRequired = top1 < config.confirmThreshold || (top1 - top2) < config.ambiguityGap

        val status = if (reviewRequired) MatchStatus.REVIEW_REQUIRED else MatchStatus.OK
        Log.i(TAG, "match: status=$status top1=$top1 top2=$top2")
        SkuMatchResult(status, rawScores, capturedImagePath)
    }

    /**
     * Placeholder JNI call: compute embedding similarity between two image paths.
     * Returns 0f when native bridge is not yet wired (MNN runtime not ready).
     * Real implementation will call NativeMnnQwenBridge.nativeComputeSimilarity().
     */
    @Suppress("UNUSED_PARAMETER")
    private fun nativeComputeSimilarity(handle: Long, imagePath: String, refPath: String): Float {
        // TODO: wire to NativeMnnQwenBridge.nativeComputeSimilarity(handle, imagePath, refPath)
        // Until physical hardware + JNI stub is available this returns 0f,
        // which causes match() to return MNN_PENDING via the isLoaded() guard above.
        return 0f
    }
}
