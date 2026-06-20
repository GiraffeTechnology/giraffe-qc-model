package com.giraffetechnology.qc

import android.content.Context
import com.giraffetechnology.qc.camera.UvcCameraFrameSource
import com.giraffetechnology.qc.capture.PendingTargetDetector
import com.giraffetechnology.qc.qwen.MnnQwenInspector
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.sku.ApiSkuRepository
import com.giraffetechnology.qc.sku.MnnSkuMatcher
import com.giraffetechnology.qc.sku.SkuRepository

/**
 * Single production DI graph for the Pad app.
 * MnnRuntimeLoader is instantiated exactly once here; all consumers receive the same instance.
 * No mock or fake implementations; all fields are production classes.
 */
class PadRuntimeGraph(
    private val context: Context,
    skuApiBaseUrl: String,
) {
    val runtimeLoader: MnnRuntimeLoader    by lazy { MnnRuntimeLoader(context.applicationContext) }
    val skuRepository: SkuRepository       by lazy { ApiSkuRepository(skuApiBaseUrl) }
    val skuMatcher: MnnSkuMatcher          by lazy { MnnSkuMatcher(runtimeLoader, skuRepository) }
    val qwenInspector: MnnQwenInspector    by lazy { MnnQwenInspector(context.applicationContext, runtimeLoader) }
    val cameraSource: UvcCameraFrameSource by lazy { UvcCameraFrameSource(context.applicationContext) }
    val targetDetector: PendingTargetDetector by lazy { PendingTargetDetector() }
}
