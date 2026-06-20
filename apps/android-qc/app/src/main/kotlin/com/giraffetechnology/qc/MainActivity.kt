package com.giraffetechnology.qc

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.giraffetechnology.qc.qwen.*
import com.giraffetechnology.qc.ui.PadStatusScreen
import kotlinx.coroutines.*
import java.io.File

class MainActivity : ComponentActivity() {

    companion object { private const val TAG = "QCPadMain" }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var modelReady by mutableStateOf(false)
    private var runtimeReady by mutableStateOf(false)
    private var inspectionResult by mutableStateOf<String?>(null)
    private var isRunning by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            PadStatusScreen(
                modelReady = modelReady,
                runtimeReady = runtimeReady,
                inspectionResult = inspectionResult,
                isRunning = isRunning,
            )
        }
        scope.launch { initInspectionPipeline() }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    private suspend fun initInspectionPipeline() {
        // Search sdcard sideload paths first (flat layout); fall back to app-private dir.
        val modelDir = withContext(Dispatchers.IO) {
            ModelProvisioning.SDCARD_SIDELOAD_PATHS
                .map { File(it) }
                .firstOrNull { it.exists() && it.isDirectory }
                ?: ModelProvisioning.getModelDir(this@MainActivity)
        }
        modelReady = ModelProvisioning.isModelReady(modelDir)

        if (!modelReady) {
            val missing = ModelProvisioning.missingFiles(modelDir)
            Log.w(TAG, "Local model NOT ready at ${modelDir.absolutePath} — missing: $missing")
            Log.w(TAG, "  Deploy: adb push <model-dir>/. /sdcard/qwen3_vl_4b_mnn/")
            return
        }

        val runtimeLoader = MnnRuntimeLoader(this)
        isRunning = true
        runtimeReady = withContext(Dispatchers.Default) { runtimeLoader.loadModel(modelDir) }
        isRunning = false

        val config = RouterConfig(
            mode                = "local_only",
            onDeviceEnabled     = true,
            onDeviceTimeoutMs   = 60_000L,
            minConfidence       = 0.82f,
            onDeviceFailIsFinal = true,
            cloudEnabled        = false,
            allowSendImages     = false,
        )
        val onDeviceInspector = MnnQwenInspector(
            context       = this,
            runtimeLoader = runtimeLoader,
            modelName     = "Qwen3-VL-4B-Instruct-MNN",
        )
        val router = QwenInspectionRouter(onDeviceInspector, config = config)
        Log.i(TAG, "Inspection pipeline ready: engine=${onDeviceInspector.engineName}")
    }
}
