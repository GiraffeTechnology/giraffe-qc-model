package com.giraffetechnology.qc

import android.app.Activity
import android.os.Bundle
import android.util.Log
import com.giraffetechnology.qc.qwen.*
import kotlinx.coroutines.*

class MainActivity : Activity() {

    companion object { private const val TAG = "QCMain" }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.i(TAG, "QC app started")
        scope.launch { initInspectionPipeline() }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    private suspend fun initInspectionPipeline() {
        val runtimeLoader = MnnRuntimeLoader(this)
        val config = RouterConfig(
            onDeviceEnabled    = true,
            onDeviceTimeoutMs  = 10_000L,
            cloudEnabled       = false,
            minConfidence      = 0.82f,
            onDeviceFailIsFinal = true,
        )
        val onDeviceInspector = MnnQwenInspector(this, runtimeLoader)
        val router = QwenInspectionRouter(onDeviceInspector, config = config)
        Log.i(TAG, "Inspection pipeline ready: engine=${onDeviceInspector.engineName} router=$router")
        // UI wiring happens here once views are added
    }
}
