package com.giraffetechnology.qc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.compose.material3.MaterialTheme
import com.giraffetechnology.qc.admin.AdminLoginState
import com.giraffetechnology.qc.ui.OperatorQcWorkScreen
import com.giraffetechnology.qc.ui.admin.AdminBundleScreen
import com.giraffetechnology.qc.ui.admin.AdminHealthScreen
import com.giraffetechnology.qc.ui.admin.AdminHomeScreen
import com.giraffetechnology.qc.ui.admin.AdminLoginScreen
import com.giraffetechnology.qc.ui.admin.AdminProbationScreen
import com.giraffetechnology.qc.ui.admin.AdminResultsScreen
import com.giraffetechnology.qc.ui.admin.AdminSkuScreen
import com.giraffetechnology.qc.ui.admin.AdminStandardScreen
import com.giraffetechnology.qc.ui.admin.AdminWorkstationScreen
import com.giraffetechnology.qc.ui.OperatorResultReviewScreen
import com.giraffetechnology.qc.ui.OperatorSyncStatusScreen
import com.giraffetechnology.qc.ui.OperatorTaskSelectionScreen
import com.giraffetechnology.qc.ui.QcCaptureScreen
import com.giraffetechnology.qc.ui.ResultScreen
import com.giraffetechnology.qc.ui.WelcomeScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Build provenance (P0-7): ties any installed APK back to its exact commit.
        android.util.Log.i(
            "BuildProvenance",
            "commit=${BuildConfig.GIT_COMMIT_SHA} branch=${BuildConfig.GIT_BRANCH} " +
                "builtAt=${BuildConfig.BUILD_TIMESTAMP}",
        )
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
            onAdministrator    = {
                // Skip login if an admin session is already bound this run.
                screen = if (PadRuntimeGraph.adminLoginController.state.value
                        is AdminLoginState.LoggedIn
                ) PadScreen.AdminHome else PadScreen.AdminLogin
            },
            onOperator         = { screen = PadScreen.OperatorTaskSelection },
        )

        // ── Administrator module (WS3) ──────────────────────────────────────
        is PadScreen.AdminLogin -> AdminLoginScreen(
            controller         = PadRuntimeGraph.adminLoginController,
            languageController = PadRuntimeGraph.languageController,
            onLoggedIn         = { screen = PadScreen.AdminHome },
            onBack             = { screen = PadScreen.Welcome },
        )

        is PadScreen.AdminHome -> AdminHomeScreen(
            loginController    = PadRuntimeGraph.adminLoginController,
            languageController = PadRuntimeGraph.languageController,
            onOpenSkus         = { screen = PadScreen.AdminSkus },
            onOpenBundles      = { screen = PadScreen.AdminBundles },
            onOpenWorkstations = { screen = PadScreen.AdminWorkstations },
            onOpenHealth       = { screen = PadScreen.AdminHealth },
            onOpenProbation    = { screen = PadScreen.AdminProbation },
            onOpenResults      = { screen = PadScreen.AdminResults },
            onLogout           = {
                PadRuntimeGraph.adminLoginController.logout()
                screen = PadScreen.Welcome
            },
        )

        is PadScreen.AdminSkus -> AdminSkuScreen(
            controller         = PadRuntimeGraph.adminSkuController,
            languageController = PadRuntimeGraph.languageController,
            onOpenStandard     = { skuId -> screen = PadScreen.AdminStandard(skuId) },
            onBack             = { screen = PadScreen.AdminHome },
        )

        is PadScreen.AdminStandard -> AdminStandardScreen(
            skuId              = s.skuId,
            skuController      = PadRuntimeGraph.adminSkuController,
            standardController = PadRuntimeGraph.adminStandardController,
            client             = PadRuntimeGraph.adminApiClient,
            languageController = PadRuntimeGraph.languageController,
            onPublish          = { screen = PadScreen.AdminBundles },
            onBack             = { screen = PadScreen.AdminSkus },
        )

        is PadScreen.AdminBundles -> AdminBundleScreen(
            bundleController   = PadRuntimeGraph.adminBundleController,
            skuController      = PadRuntimeGraph.adminSkuController,
            languageController = PadRuntimeGraph.languageController,
            onBack             = { screen = PadScreen.AdminHome },
        )

        is PadScreen.AdminWorkstations -> AdminWorkstationScreen(
            workstationController = PadRuntimeGraph.adminWorkstationController,
            bundleController      = PadRuntimeGraph.adminBundleController,
            languageController    = PadRuntimeGraph.languageController,
            onBack                = { screen = PadScreen.AdminHome },
        )

        is PadScreen.AdminHealth -> AdminHealthScreen(
            controller         = PadRuntimeGraph.adminHealthController,
            languageController = PadRuntimeGraph.languageController,
            onBack             = { screen = PadScreen.AdminHome },
        )

        is PadScreen.AdminProbation -> AdminProbationScreen(
            controller         = PadRuntimeGraph.adminProbationController,
            languageController = PadRuntimeGraph.languageController,
            onBack             = { screen = PadScreen.AdminHome },
        )

        is PadScreen.AdminResults -> AdminResultsScreen(
            controller         = PadRuntimeGraph.adminResultsController,
            languageController = PadRuntimeGraph.languageController,
            onBack             = { screen = PadScreen.AdminHome },
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
            languageController      = PadRuntimeGraph.languageController,
            onTaskConfirmed         = { task -> screen = PadScreen.QcCapture(task) },
        )

        is PadScreen.QcCapture -> QcCaptureScreen(
            task                  = s.task,
            autoCaptureController = PadRuntimeGraph.autoCaptureController,
            runtimeLoader         = PadRuntimeGraph.runtimeLoader,
            cameraXController     = PadRuntimeGraph.cameraXCaptureController,
            languageController    = PadRuntimeGraph.languageController,
            inspectionCoordinator = PadRuntimeGraph.inspectionCoordinator,
            onInspectionResult    = { result -> screen = PadScreen.Result(s.task, result) },
            onBack                = { screen = PadScreen.OperatorTaskSelection },
        )

        is PadScreen.Result -> ResultScreen(
            task     = s.task,
            result   = s.result,
            languageController = PadRuntimeGraph.languageController,
            onRetake = { screen = PadScreen.QcCapture(s.task) },
            onDone   = { screen = PadScreen.OperatorTaskSelection },
        )
    }
}
