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
import com.giraffetechnology.qc.jetson.JetsonLanClient
import com.giraffetechnology.qc.jetson.JetsonPairingStore
import com.giraffetechnology.qc.jetson.JetsonQwenInspector
import com.giraffetechnology.qc.jetson.JetsonRuntimeMonitor
import com.giraffetechnology.qc.jetson.JetsonServerRelay
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
import com.giraffetechnology.qc.admin.AdminApiClient
import com.giraffetechnology.qc.admin.AdminBundleController
import com.giraffetechnology.qc.admin.AdminHealthController
import com.giraffetechnology.qc.admin.AdminLoginController
import com.giraffetechnology.qc.admin.AdminProbationController
import com.giraffetechnology.qc.admin.AdminResultsController
import com.giraffetechnology.qc.admin.AdminSkuController
import com.giraffetechnology.qc.admin.AdminStandardController
import com.giraffetechnology.qc.admin.AdminWorkstationController
import com.giraffetechnology.qc.admin.AndroidPadHealthProbe
import com.giraffetechnology.qc.sku.ApiSkuRepository
import com.giraffetechnology.qc.sku.MnnRuntime
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
 * @property modelRoot Legacy MNN model directory, default `/sdcard/qwen_2b_mnn`.
 *   Only consulted when [legacyMnnRuntimeEnabled] is true.
 * @property loadModelOnInit If true and [legacyMnnRuntimeEnabled], kicks off
 *   the legacy MNN model load in the background at init.
 * @property legacyMnnRuntimeEnabled Gate for the retired on-device MNN
 *   inference path (WS4). **Default false** -- Jetson LAN inference
 *   ([com.giraffetechnology.qc.jetson.JetsonQwenInspector]) is the default
 *   inference path for a fresh install. MNN code is retained (not deleted)
 *   as a possible offline fallback, but must never be what a fresh install
 *   or a production-marked build runs by default -- this flag is the single
 *   place that decides which one is active, and it defaults from
 *   [BuildConfig.LEGACY_MNN_RUNTIME_ENABLED] (itself `false` in
 *   `defaultConfig`), not from a per-call default that could silently drift.
 *
 * The primary frame source is the external USB UVC camera (production line). The
 * built-in CameraX camera is a secondary source obtained on demand via
 * [PadRuntimeGraph.createCameraXFrameSource] (it needs a LifecycleOwner).
 */
data class PadRuntimeConfig(
    val modelRoot: String = MnnRuntimeConfig.DEFAULT_MODEL_ROOT,
    val loadModelOnInit: Boolean = true,
    val legacyMnnRuntimeEnabled: Boolean = BuildConfig.LEGACY_MNN_RUNTIME_ENABLED,
)

/**
 * Singleton entry point for all production runtime objects.
 *
 * Rules:
 * - The active inference runtime (Jetson by default, or legacy MNN behind
 *   [PadRuntimeConfig.legacyMnnRuntimeEnabled]) is instantiated exactly once.
 * - MainActivity must not instantiate any of these directly.
 * - No test-only fake/mock may be used under src/main.
 *
 * Production pipeline assembled here (default, Jetson):
 *   real frame source (UVC / CameraX) → target detector (full-frame pass-through)
 *   → JetsonQwenInspector (LAN call to the paired Xavier NX) → PadInspectionCoordinator.
 * The coordinator's existing fail-closed behavior (empty standard / not-ready
 * runtime → review_required / MNN_PENDING) is preserved unchanged -- it only
 * depends on the [MnnRuntime] / [QwenInspector] interfaces, not on which
 * concrete implementation is wired in here.
 */
object PadRuntimeGraph {
    private const val TAG = "PadRuntimeGraph"

    private val bgScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile private var _initialized = false
    @Volatile private var _config: PadRuntimeConfig = PadRuntimeConfig()
    @Volatile private var _loader: MnnRuntime? = null
    @Volatile private var _jetsonPairingStore: JetsonPairingStore? = null
    @Volatile private var _jetsonClient: JetsonLanClient? = null
    @Volatile private var _jetsonRuntimeMonitor: JetsonRuntimeMonitor? = null
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
    @Volatile private var _adminApiClient: AdminApiClient? = null
    @Volatile private var _adminLoginController: AdminLoginController? = null
    @Volatile private var _adminSkuController: AdminSkuController? = null
    @Volatile private var _adminStandardController: AdminStandardController? = null
    @Volatile private var _adminBundleController: AdminBundleController? = null
    @Volatile private var _adminWorkstationController: AdminWorkstationController? = null
    @Volatile private var _adminResultsController: AdminResultsController? = null
    @Volatile private var _adminProbationController: AdminProbationController? = null
    @Volatile private var _adminHealthController: AdminHealthController? = null

    fun init(context: Context) = init(context, PadRuntimeConfig())

    fun init(context: Context, config: PadRuntimeConfig) {
        if (_initialized) return
        synchronized(this) {
            if (_initialized) return
            _config = config
            val appContext = context.applicationContext

            // Jetson objects are always constructed (cheap: SharedPreferences
            // + an idle HTTP client) so pairing is available on the Pad
            // regardless of which runtime is active -- only .start() (health
            // polling) and being wired as *the* active runtime/inspector are
            // gated by legacyMnnRuntimeEnabled.
            val jetsonPairingStore = JetsonPairingStore(appContext)
            _jetsonPairingStore = jetsonPairingStore
            val jetsonClient = JetsonLanClient()
            _jetsonClient = jetsonClient
            val jetsonRuntimeMonitor = JetsonRuntimeMonitor(
                jetsonPairingStore,
                jetsonClient,
                serverRelay = JetsonServerRelay(BuildConfig.SKU_API_BASE_URL),
            )
            _jetsonRuntimeMonitor = jetsonRuntimeMonitor

            val runtime: MnnRuntime
            val inspector: QwenInspector
            if (config.legacyMnnRuntimeEnabled) {
                Log.w(TAG, "legacyMnnRuntimeEnabled=true — MNN is the active inference path, not Jetson")
                val loader = MnnRuntimeLoader(appContext, MnnRuntimeConfig(modelRoot = config.modelRoot))
                runtime = loader
                inspector = MnnQwenInspector(appContext, loader)
                if (config.loadModelOnInit) {
                    bgScope.launch {
                        val ready = runCatching { loader.loadModel() }.getOrElse { e ->
                            Log.e(TAG, "Legacy MNN model load failed: ${e.message}"); false
                        }
                        Log.i(TAG, "Legacy MNN startup model load complete — ready=$ready")
                    }
                }
            } else {
                jetsonRuntimeMonitor.start()
                runtime = jetsonRuntimeMonitor
                inspector = JetsonQwenInspector(jetsonPairingStore, jetsonClient)
            }
            _loader = runtime
            _qwenInspector = inspector

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

            _inspectionCoordinator = PadInspectionCoordinator(inspector, runtime)

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

            // Administrator module (WS3): real backend client + controllers.
            val adminClient = AdminApiClient(BuildConfig.SKU_API_BASE_URL)
            _adminApiClient = adminClient
            _adminLoginController = AdminLoginController(adminClient)
            _adminSkuController = AdminSkuController(adminClient)
            _adminStandardController = AdminStandardController(adminClient)
            _adminBundleController = AdminBundleController(adminClient)
            _adminWorkstationController = AdminWorkstationController(adminClient)
            _adminResultsController = AdminResultsController(adminClient)
            _adminProbationController = AdminProbationController(adminClient)
            _adminHealthController = AdminHealthController(
                client = adminClient,
                probe = AndroidPadHealthProbe(appContext),
                runtimeState = loader.runtimeState,
            )

            _initialized = true
        }
    }

    /**
     * Builds a CameraX built-in-camera frame source bound to [owner]. Used for
     * on-device end-to-end verification when the UVC camera is unavailable.
     */
    fun createCameraXFrameSource(context: Context, owner: LifecycleOwner): CameraXFrameSource =
        CameraXFrameSource(context.applicationContext, owner)

    /** The active inference runtime -- [JetsonRuntimeMonitor] by default, or the legacy [MnnRuntimeLoader] behind [PadRuntimeConfig.legacyMnnRuntimeEnabled]. */
    val runtimeLoader: MnnRuntime
        get() = checkNotNull(_loader) { notInitMsg() }

    /** Always available regardless of [PadRuntimeConfig.legacyMnnRuntimeEnabled] -- pairing works even if MNN is the active runtime. */
    val jetsonPairingStore: JetsonPairingStore
        get() = checkNotNull(_jetsonPairingStore) { notInitMsg() }

    val jetsonClient: JetsonLanClient
        get() = checkNotNull(_jetsonClient) { notInitMsg() }

    val jetsonRuntimeMonitor: JetsonRuntimeMonitor
        get() = checkNotNull(_jetsonRuntimeMonitor) { notInitMsg() }

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

    val adminApiClient: AdminApiClient
        get() = checkNotNull(_adminApiClient) { notInitMsg() }

    val adminLoginController: AdminLoginController
        get() = checkNotNull(_adminLoginController) { notInitMsg() }

    val adminSkuController: AdminSkuController
        get() = checkNotNull(_adminSkuController) { notInitMsg() }

    val adminStandardController: AdminStandardController
        get() = checkNotNull(_adminStandardController) { notInitMsg() }

    val adminBundleController: AdminBundleController
        get() = checkNotNull(_adminBundleController) { notInitMsg() }

    val adminWorkstationController: AdminWorkstationController
        get() = checkNotNull(_adminWorkstationController) { notInitMsg() }

    val adminResultsController: AdminResultsController
        get() = checkNotNull(_adminResultsController) { notInitMsg() }

    val adminProbationController: AdminProbationController
        get() = checkNotNull(_adminProbationController) { notInitMsg() }

    val adminHealthController: AdminHealthController
        get() = checkNotNull(_adminHealthController) { notInitMsg() }

    private fun notInitMsg() = "PadRuntimeGraph.init(context) must be called before accessing this"
}
