package com.giraffetechnology.qc

import android.content.Context
import com.giraffetechnology.qc.camera.CameraUnavailableFrameSource
import com.giraffetechnology.qc.camera.CameraFrameSource
import com.giraffetechnology.qc.camera.CameraXCaptureController
import com.giraffetechnology.qc.capture.AutoCaptureController
import com.giraffetechnology.qc.capture.PendingTargetDetector
import com.giraffetechnology.qc.capture.TargetDetector
import com.giraffetechnology.qc.qwen.MnnQwenInspector
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.qwen.QwenInspector
import com.giraffetechnology.qc.sku.ApiSkuRepository
import com.giraffetechnology.qc.sku.MnnSkuMatcher
import com.giraffetechnology.qc.sku.PadInspectionCoordinator
import com.giraffetechnology.qc.sku.SkuMatcher
import com.giraffetechnology.qc.sku.SkuRepository
import com.giraffetechnology.qc.sku.TaskSelectionController
import com.giraffetechnology.qc.BuildConfig

/**
 * Singleton entry point for all production runtime objects.
 *
 * Rules:
 * - MnnRuntimeLoader is instantiated exactly once.
 * - MainActivity must not instantiate any of these directly.
 * - No test-only fake/mock may be used under src/main.
 * - Production-safe placeholders (PendingTargetDetector, CameraUnavailableFrameSource,
 *   MnnSkuMatcher returning REVIEW_REQUIRED) are allowed and explicit.
 */
object PadRuntimeGraph {
    @Volatile private var _initialized = false
    @Volatile private var _loader: MnnRuntimeLoader? = null
    @Volatile private var _skuRepo: SkuRepository? = null
    @Volatile private var _skuMatcher: SkuMatcher? = null
    @Volatile private var _taskSelectionController: TaskSelectionController? = null
    @Volatile private var _cameraFrameSource: CameraFrameSource? = null
    @Volatile private var _targetDetector: TargetDetector? = null
    @Volatile private var _autoCaptureController: AutoCaptureController? = null
    @Volatile private var _qwenInspector: QwenInspector? = null
    @Volatile private var _inspectionCoordinator: PadInspectionCoordinator? = null
    @Volatile private var _cameraXCaptureController: CameraXCaptureController? = null

    fun init(context: Context) {
        if (_initialized) return
        synchronized(this) {
            if (_initialized) return

            val loader = MnnRuntimeLoader(context.applicationContext)
            _loader = loader

            val skuRepo = ApiSkuRepository(BuildConfig.SKU_API_BASE_URL)
            _skuRepo = skuRepo

            val matcher = MnnSkuMatcher()
            _skuMatcher = matcher

            _taskSelectionController = TaskSelectionController(skuRepo, matcher)

            // Camera: use CameraUnavailableFrameSource for frame-stream consumers.
            _cameraFrameSource = CameraUnavailableFrameSource()

            // Target detector: use PendingTargetDetector until MNN visual model is provisioned.
            val detector = PendingTargetDetector()
            _targetDetector = detector

            _autoCaptureController = AutoCaptureController(detector = detector)

            val inspector = MnnQwenInspector(context.applicationContext, loader)
            _qwenInspector = inspector

            _inspectionCoordinator = PadInspectionCoordinator(inspector, loader)

            // CameraX still-image capture — bind() is called from the capture screen composable.
            _cameraXCaptureController = CameraXCaptureController(context.applicationContext)

            _initialized = true
        }
    }

    val runtimeLoader: MnnRuntimeLoader
        get() = checkNotNull(_loader) { notInitMsg() }

    val skuRepository: SkuRepository
        get() = checkNotNull(_skuRepo) { notInitMsg() }

    val skuMatcher: SkuMatcher
        get() = checkNotNull(_skuMatcher) { notInitMsg() }

    val taskSelectionController: TaskSelectionController
        get() = checkNotNull(_taskSelectionController) { notInitMsg() }

    val cameraFrameSource: CameraFrameSource
        get() = checkNotNull(_cameraFrameSource) { notInitMsg() }

    val targetDetector: TargetDetector
        get() = checkNotNull(_targetDetector) { notInitMsg() }

    val autoCaptureController: AutoCaptureController
        get() = checkNotNull(_autoCaptureController) { notInitMsg() }

    val qwenInspector: QwenInspector
        get() = checkNotNull(_qwenInspector) { notInitMsg() }

    val inspectionCoordinator: PadInspectionCoordinator
        get() = checkNotNull(_inspectionCoordinator) { notInitMsg() }

    val cameraXCaptureController: CameraXCaptureController
        get() = checkNotNull(_cameraXCaptureController) { notInitMsg() }

    private fun notInitMsg() = "PadRuntimeGraph.init(context) must be called before accessing this"
}
