package com.giraffetechnology.qc

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import com.giraffetechnology.qc.capture.*
import com.giraffetechnology.qc.camera.MockCameraFrameSource
import com.giraffetechnology.qc.qwen.*
import com.giraffetechnology.qc.sku.*
import com.giraffetechnology.qc.ui.*
import kotlinx.coroutines.*

class MainActivity : ComponentActivity() {

    companion object { private const val TAG = "QCPadMain" }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { QcPadApp() }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    @Composable
    private fun QcPadApp() {
        // ── MNN runtime (unchanged from existing pipeline) ──
        var mnnRuntimeState by remember { mutableStateOf<MnnRuntimeState>(MnnRuntimeState.NotReady) }
        val runtimeLoader = remember { MnnRuntimeLoader(this) }

        LaunchedEffect(Unit) {
            val modelDir = ModelProvisioning.getModelDir(this@MainActivity)
            if (!ModelProvisioning.isModelReady(modelDir)) {
                Log.w(TAG, "Local model NOT ready — MNN pending")
                return@LaunchedEffect
            }
            mnnRuntimeState = MnnRuntimeState.Loading
            val ok = withContext(Dispatchers.Default) { runtimeLoader.loadModel(modelDir) }
            mnnRuntimeState = if (ok) MnnRuntimeState.Ready else MnnRuntimeState.NotReady
            if (ok) Log.i(TAG, "MNN runtime ready")
            else    Log.w(TAG, "MNN runtime load failed — review_required path active")
        }

        // ── Navigation state ──
        var screen by remember { mutableStateOf<Screen>(Screen.Login) }
        var operatorId by remember { mutableStateOf("") }
        var confirmedTask by remember { mutableStateOf<com.giraffetechnology.qc.sku.QcTask?>(null) }

        // ── SKU / task selection ──
        val fakeRepo = remember { FakeSkuRepository() } // placeholder; real=ApiSkuRepository(baseUrl)
        val skuMatcher = remember { MnnSkuMatcher(runtimeLoader, fakeRepo) }
        val taskController = remember { TaskSelectionController(fakeRepo, skuMatcher) }
        val taskState by taskController.state.collectAsState()

        // ── Auto-capture ──
        val mockCamera = remember { MockCameraFrameSource() }
        val mockDetector = remember { MockTargetDetector.noCandidateForever() }
        val captureController = remember { AutoCaptureController(detector = mockDetector) }
        val captureState by captureController.state.collectAsState()

        when (screen) {
            Screen.Login -> LoginScreen(
                onLoginSuccess = { id ->
                    operatorId = id
                    screen = Screen.TaskSelection
                },
            )
            Screen.TaskSelection -> TaskSelectionScreen(
                state            = taskState,
                runtimeState     = mnnRuntimeState,
                onManualSearch   = { q -> scope.launch { taskController.searchByItemNumber(q) } },
                onManualConfirm  = { sku ->
                    taskController.confirmManual(sku, SkuResolutionMethod.MANUAL_ITEM_NUMBER)
                    confirmedTask = (taskController.state.value as? TaskSelectionState.TaskConfirmed)?.task
                    screen = Screen.QcCapture
                },
                onStartPhotoMatch = { taskController.startCapturingForMatch() },
                onConfirmCandidate = { candidate ->
                    taskController.confirmCandidate(candidate)
                    confirmedTask = (taskController.state.value as? TaskSelectionState.TaskConfirmed)?.task
                    screen = Screen.QcCapture
                },
                onSwitchToManual = { taskController.reset() },
            )
            Screen.QcCapture -> QcCaptureScreen(
                captureState    = captureState,
                mnnRuntimeState = mnnRuntimeState,
                cameraConnected = false, // MockCameraFrameSource starts Disconnected until start() called
                operatorId      = operatorId,
                skuName         = confirmedTask?.sku?.name ?: "",
            )
        }
    }

    private enum class Screen { Login, TaskSelection, QcCapture }
}
