package com.giraffetechnology.qc

import android.content.Context
import android.util.Log
import com.giraffetechnology.qc.camera.CameraFrameSource
import com.giraffetechnology.qc.camera.CameraXCaptureController
import com.giraffetechnology.qc.camera.CameraXFrameSource
import com.giraffetechnology.qc.camera.UvcCameraFrameSource
import com.giraffetechnology.qc.capture.AutoCaptureController
import com.giraffetechnology.qc.capture.FullFramePassthroughDetector
import com.giraffetechnology.qc.capture.TargetDetector
import com.giraffetechnology.qc.qwen.MnnQwenInspector
import com.giraffetechnology.qc.qwen.MnnRuntimeConfig
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.qwen.QwenInspector
import com.giraffetechnology.qc.contracts.SqliteStandardStore
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.operator.OperatorTaskSelectionController
import com.giraffetechnology.qc.store.AndroidSqliteStandardStore
import com.giraffetechnology.qc.store.BundleImporter
import com.giraffetechnology.qc.submit.AndroidSqliteOutboxStore
import com.giraffetechnology.qc.submit.HttpSubmissionClient
import com.giraffetechnology.qc.submit.OutboxUploader
import com.giraffetechnology.qc.submit.PadOutbox
import com.giraffetechnology.qc.sku.ApiSkuRepository
import com.giraffetechnology.qc.sku.MnnSkuMatcher
import com.giraffetechnology.qc.sku.PadInspectionCoordinator
import com.giraffetechnology.qc.sku.SkuMatcher
import com.giraffetechnology.qc.sku.SkuRepository
import com.giraffetechnology.qc.sku.TaskSelectionController
import com.giraffetechnology.qc.BuildConfig
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Runtime configuration for [PadRuntimeGraph].
 *
 * @property modelRoot Model directory, default `/sdcard/qwen_2b_mnn`.
 * @property loadModelOnInit If true, kicks off model load in the background at
 *   init so cold start drives the runtime toward Ready.
 *
 * The primary frame source is the external USB UVC camera (production line). The
 * built-in CameraX camera is a secondary source obtained on demand via
 * [PadRuntimeGraph.createCameraXFrameSource] (it needs a LifecycleOwner).
 */
data class PadRuntimeConfig(
    val modelRoot: String = MnnRuntimeConfig.DEFAULT_MODEL_ROOT,
    val loadModelOnInit: Boolean = true,
)

/**
 * Singleton entry point for all production runtime objects.
 *
 * Rules:
 * - MnnRuntimeLoader is instantiated exactly once.
 * - MainActivity must not instantiate any of these directly.
 * - No test-only fake/mock may be used under src/main.
 *
 * Production pipeline assembled here:
 *   real frame source (UVC / CameraX) → target detector (full-frame pass-through)
 *   → MnnQwenInspector → PadInspectionCoordinator.
 * The coordinator's existing fail-closed behavior (empty standard / not-ready
 * runtime → review_required / MNN_PENDING) is preserved unchanged.
 */
object PadRuntimeGraph {
    private const val TAG = "PadRuntimeGraph"

    private val bgScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile private var _initialized = false
    @Volatile private var _config: PadRuntimeConfig = PadRuntimeConfig()
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
    @Volatile private var _standardStore: AndroidSqliteStandardStore? = null
    @Volatile private var _bundleImporter: BundleImporter? = null
    @Volatile private var _operatorTaskSelectionController: OperatorTaskSelectionController? = null
    @Volatile private var _languageController: LanguageController? = null
    @Volatile private var _outbox: PadOutbox? = null
    @Volatile private var _outboxUploader: OutboxUploader? = null

    fun init(context: Context) = init(context, PadRuntimeConfig())

    fun init(context: Context, config: PadRuntimeConfig) {
        if (_initialized) return
        synchronized(this) {
            if (_initialized) return
            _config = config
            val appContext = context.applicationContext

            val loader = MnnRuntimeLoader(appContext, MnnRuntimeConfig(modelRoot = config.modelRoot))
            _loader = loader

            val skuRepo = ApiSkuRepository(BuildConfig.SKU_API_BASE_URL)
            _skuRepo = skuRepo

            val matcher = MnnSkuMatcher()
            _skuMatcher = matcher

            _taskSelectionController = TaskSelectionController(skuRepo, matcher)

            // Frame source: external USB UVC camera on the production line. The
            // CameraX built-in source is created on demand (it needs a
            // LifecycleOwner) via createCameraXFrameSource().
            _cameraFrameSource = UvcCameraFrameSource(appContext)

            // Target detector: documented full-frame pass-through until a real
            // object detector is provisioned (Work Item 3). Not a fake detection.
            val detector = FullFramePassthroughDetector()
            _targetDetector = detector

            _autoCaptureController = AutoCaptureController(detector = detector)

            val inspector = MnnQwenInspector(appContext, loader)
            _qwenInspector = inspector

            _inspectionCoordinator = PadInspectionCoordinator(inspector, loader)

            _cameraXCaptureController = CameraXCaptureController(appContext)

            // Offline on-device standards store (S5 §14) + its consumers.
            val standardStore = AndroidSqliteStandardStore(appContext)
            _standardStore = standardStore
            _bundleImporter = BundleImporter(standardStore)
            _operatorTaskSelectionController = OperatorTaskSelectionController(standardStore)

            // i18n seam: resolve the initial locale from the device language list
            // with English fallback; explicit operator selection takes over later.
            val deviceTags = run {
                val locales = appContext.resources.configuration.locales
                (0 until locales.size()).map { locales.get(it).toLanguageTag() }
            }
            _languageController = LanguageController(deviceLanguageTags = deviceTags)

            // Result outbox (S6 §9): offline-persisted results drained to the
            // Server over the factory LAN. This carries result metadata only —
            // never a cloud QC-inference call.
            val outbox = PadOutbox(AndroidSqliteOutboxStore(appContext))
            _outbox = outbox
            _outboxUploader = OutboxUploader(outbox, HttpSubmissionClient(BuildConfig.SKU_API_BASE_URL))

            _initialized = true

            if (config.loadModelOnInit) {
                bgScope.launch {
                    val ready = runCatching { loader.loadModel() }.getOrElse { e ->
                        Log.e(TAG, "Model load failed: ${e.message}"); false
                    }
                    Log.i(TAG, "Startup model load complete — ready=$ready")
                }
            }
        }
    }

    /**
     * Builds a CameraX built-in-camera frame source bound to [owner]. Used for
     * on-device end-to-end verification when the UVC camera is unavailable.
     */
    fun createCameraXFrameSource(context: Context, owner: LifecycleOwner): CameraXFrameSource =
        CameraXFrameSource(context.applicationContext, owner)

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

    val standardStore: SqliteStandardStore
        get() = checkNotNull(_standardStore) { notInitMsg() }

    val bundleImporter: BundleImporter
        get() = checkNotNull(_bundleImporter) { notInitMsg() }

    val operatorTaskSelectionController: OperatorTaskSelectionController
        get() = checkNotNull(_operatorTaskSelectionController) { notInitMsg() }

    val languageController: LanguageController
        get() = checkNotNull(_languageController) { notInitMsg() }

    val outbox: PadOutbox
        get() = checkNotNull(_outbox) { notInitMsg() }

    val outboxUploader: OutboxUploader
        get() = checkNotNull(_outboxUploader) { notInitMsg() }

    private fun notInitMsg() = "PadRuntimeGraph.init(context) must be called before accessing this"
}
