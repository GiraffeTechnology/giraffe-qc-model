package com.giraffetechnology.qc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.compose.material3.MaterialTheme
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask
import com.giraffetechnology.qc.ui.QcCaptureScreen
import com.giraffetechnology.qc.ui.ResultScreen
import com.giraffetechnology.qc.ui.TaskSelectionScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PadRuntimeGraph.init(this)
        setContent {
            MaterialTheme {
                PadApp()
            }
        }
    }
}

@Composable
private fun PadApp() {
    var screen by remember { mutableStateOf<PadScreen>(PadScreen.TaskSelection) }

    when (val s = screen) {
        is PadScreen.TaskSelection -> TaskSelectionScreen(
            taskSelectionController = PadRuntimeGraph.taskSelectionController,
            runtimeLoader           = PadRuntimeGraph.runtimeLoader,
            skuRepository           = PadRuntimeGraph.skuRepository as? com.giraffetechnology.qc.sku.ApiSkuRepository,
            onTaskConfirmed         = { task -> screen = PadScreen.QcCapture(task) },
        )

        is PadScreen.QcCapture -> QcCaptureScreen(
            task                 = s.task,
            autoCaptureController = PadRuntimeGraph.autoCaptureController,
            runtimeLoader        = PadRuntimeGraph.runtimeLoader,
            onInspectionResult   = { result ->
                screen = PadScreen.Result(s.task, result)
            },
            onBack               = { screen = PadScreen.TaskSelection },
        )

        is PadScreen.Result -> ResultScreen(
            task     = s.task,
            result   = s.result,
            onRetake = { screen = PadScreen.QcCapture(s.task) },
            onDone   = { screen = PadScreen.TaskSelection },
        )
    }
}
