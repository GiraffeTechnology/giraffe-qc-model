package com.giraffetechnology.qc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.compose.material3.MaterialTheme
import com.giraffetechnology.qc.ui.AdministratorInfoScreen
import com.giraffetechnology.qc.ui.OperatorQcWorkScreen
import com.giraffetechnology.qc.ui.OperatorResultReviewScreen
import com.giraffetechnology.qc.ui.OperatorSyncStatusScreen
import com.giraffetechnology.qc.ui.OperatorTaskSelectionScreen
import com.giraffetechnology.qc.ui.QcCaptureScreen
import com.giraffetechnology.qc.ui.ResultScreen
import com.giraffetechnology.qc.ui.WelcomeScreen

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
    var screen by remember { mutableStateOf<PadScreen>(PadScreen.Welcome) }

    when (val s = screen) {
        is PadScreen.Welcome -> WelcomeScreen(
            languageController = PadRuntimeGraph.languageController,
            onAdministrator    = { screen = PadScreen.AdministratorInfo },
            onOperator         = { screen = PadScreen.OperatorTaskSelection },
        )

        is PadScreen.AdministratorInfo -> AdministratorInfoScreen(
            languageController = PadRuntimeGraph.languageController,
            onBack             = { screen = PadScreen.Welcome },
        )

        is PadScreen.OperatorTaskSelection -> OperatorTaskSelectionScreen(
            controller         = PadRuntimeGraph.operatorTaskSelectionController,
            languageController = PadRuntimeGraph.languageController,
            onTaskConfirmed    = { task -> screen = PadScreen.QcWork(task) },
            onBack             = { screen = PadScreen.Welcome },
        )

        is PadScreen.QcWork -> OperatorQcWorkScreen(
            task                  = s.task,
            languageController    = PadRuntimeGraph.languageController,
            autoCaptureController = PadRuntimeGraph.autoCaptureController,
            runtimeLoader         = PadRuntimeGraph.runtimeLoader,
            cameraXController     = PadRuntimeGraph.cameraXCaptureController,
            inspectionCoordinator = PadRuntimeGraph.inspectionCoordinator,
            onInspectionResult    = { result -> screen = PadScreen.ResultReview(s.task, result) },
            onBack                = { screen = PadScreen.OperatorTaskSelection },
        )

        is PadScreen.ResultReview -> OperatorResultReviewScreen(
            task               = s.task,
            result             = s.result,
            languageController = PadRuntimeGraph.languageController,
            outbox             = PadRuntimeGraph.outbox,
            onSubmitted        = { screen = PadScreen.SyncStatus },
            onRetake           = { screen = PadScreen.QcWork(s.task) },
        )

        is PadScreen.SyncStatus -> OperatorSyncStatusScreen(
            languageController = PadRuntimeGraph.languageController,
            outbox             = PadRuntimeGraph.outbox,
            uploader           = PadRuntimeGraph.outboxUploader,
            onBack             = { screen = PadScreen.OperatorTaskSelection },
        )

        // Legacy backend-LAN SKU search flow, retained behind the online task path.
        is PadScreen.TaskSelection -> com.giraffetechnology.qc.ui.TaskSelectionScreen(
            taskSelectionController = PadRuntimeGraph.taskSelectionController,
            runtimeLoader           = PadRuntimeGraph.runtimeLoader,
            skuRepository           = PadRuntimeGraph.skuRepository
                as? com.giraffetechnology.qc.sku.ApiSkuRepository,
            onTaskConfirmed         = { task -> screen = PadScreen.QcCapture(task) },
        )

        is PadScreen.QcCapture -> QcCaptureScreen(
            task                  = s.task,
            autoCaptureController = PadRuntimeGraph.autoCaptureController,
            runtimeLoader         = PadRuntimeGraph.runtimeLoader,
            cameraXController     = PadRuntimeGraph.cameraXCaptureController,
            inspectionCoordinator = PadRuntimeGraph.inspectionCoordinator,
            onInspectionResult    = { result -> screen = PadScreen.Result(s.task, result) },
            onBack                = { screen = PadScreen.OperatorTaskSelection },
        )

        is PadScreen.Result -> ResultScreen(
            task     = s.task,
            result   = s.result,
            onRetake = { screen = PadScreen.QcCapture(s.task) },
            onDone   = { screen = PadScreen.OperatorTaskSelection },
        )
    }
}
