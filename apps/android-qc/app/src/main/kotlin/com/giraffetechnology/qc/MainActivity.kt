package com.giraffetechnology.qc

import android.app.Activity
import android.os.Bundle
import android.util.Log
import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.*

class MainActivity : Activity() {

    companion object { private const val TAG = "QCPadMain" }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "GiraffeQC Android Pad started")
        Log.i(TAG, "Engine: Local Qwen3-VL-4B MNN")
        Log.i(TAG, "Mode: Offline Pad")
        Log.i(TAG, "Cloud: Disabled")
        Log.i(TAG, "Network: Not used")
        scope.launch { initInspectionPipeline() }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    private suspend fun initInspectionPipeline() {
        val modelDir = ModelProvisioning.getModelDir(this)
        val modelReady = ModelProvisioning.isModelReady(modelDir)

        if (modelReady) {
            Log.i(TAG, "Local model ready: $modelDir")
        } else {
            val missing = ModelProvisioning.missingFiles(modelDir)
            Log.w(TAG, "Local model NOT ready — missing files: $missing")
            Log.w(TAG, "Result will be review_required until model is provisioned via:")
            Log.w(TAG, "  adb push ./Qwen3-VL-4B-Instruct-MNN/ /sdcard/qwen3_vl_4b_mnn/")
        }

        val runtimeLoader = MnnRuntimeLoader(this)
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
        // PadStatusScreen composable wires here once Compose setContent is added
    }
}
