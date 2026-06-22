package com.giraffetechnology.qc.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.giraffetechnology.qc.camera.CameraXCaptureController
import com.giraffetechnology.qc.capture.*
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.sku.*
import kotlinx.coroutines.launch

internal enum class CameraPermissionState { Checking, Granted, Denied }

/** Maps an Android runtime permission result to CameraPermissionState. Extracted for unit testing. */
internal fun resolvePermissionState(isGranted: Boolean): CameraPermissionState =
    if (isGranted) CameraPermissionState.Granted else CameraPermissionState.Denied

/**
 * QC Capture screen — landscape Pad layout.
 *
 * Left 3/4  = CameraX live preview (only after camera permission granted).
 * Right 1/4 = SKU info + capture state + action buttons.
 *
 * Camera permission is checked before CameraPreviewPane is composed so that
 * CameraXCaptureController.bind() is never called without CAMERA permission.
 * Manual Capture is enabled only when permission is Granted AND isCameraReady.
 */
@Composable
fun QcCaptureScreen(
    task: QcTask,
    autoCaptureController: AutoCaptureController,
    runtimeLoader: MnnRuntimeLoader,
    cameraXController: CameraXCaptureController,
    inspectionCoordinator: PadInspectionCoordinator? = null,
    onInspectionResult: (PadInspectionResult) -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val captureState by autoCaptureController.state.collectAsState()
    val runtimeState by runtimeLoader.runtimeState.collectAsState()
    val isCameraReady by cameraXController.isReady.collectAsState()

    val context = LocalContext.current

    // Check permission synchronously on first composition so the initial state is accurate.
    // CameraPreviewPane is only composed (and bind() only called) when state is Granted.
    var cameraPermState by remember {
        val granted = ContextCompat.checkSelfPermission(
            context, Manifest.permission.CAMERA,
        ) == PackageManager.PERMISSION_GRANTED
        mutableStateOf(if (granted) CameraPermissionState.Granted else CameraPermissionState.Checking)
    }

    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        cameraPermState = resolvePermissionState(granted)
    }

    // captureError is cleared on each new manual capture attempt and set on failure.
    var captureError by remember { mutableStateOf<String?>(null) }

    // Auto-capture path: when AutoCapture produces a photo, run local inspection.
    LaunchedEffect(captureState) {
        if (captureState is AutoCaptureState.Captured) {
            val photo = (captureState as AutoCaptureState.Captured).capture
            val result = inspectionCoordinator?.inspect(task, photo)
                ?: PadInspectionResult(
                    overallResult      = "MNN_PENDING",
                    reason             = "Inspection coordinator not available",
                    modelName          = "Qwen3-VL-2B-Instruct-MNN",
                    localOnly          = true,
                    cloudInferenceUsed = false,
                    capturedImagePath  = photo.rawImagePath,
                )
            onInspectionResult(result)
        }
    }

    Row(modifier = Modifier.fillMaxSize()) {
        // ── Left 3/4: camera preview — shown only after permission is granted ──────────────────────
        Box(
            modifier = Modifier
                .weight(3f)
                .fillMaxHeight()
                .background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            when (cameraPermState) {
                CameraPermissionState.Granted -> {
                    BoxWithConstraints(contentAlignment = Alignment.Center) {
                        val (previewW, previewH) = fitAspect43(maxWidth.value, maxHeight.value)
                        Box(
                            modifier = Modifier
                                .size(width = previewW.dp, height = previewH.dp)
                                .border(2.dp, Color.DarkGray),
                            contentAlignment = Alignment.Center,
                        ) {
                            CameraPreviewPane(
                                controller = cameraXController,
                                modifier   = Modifier.fillMaxSize(),
                            )
                        }
                    }
                    if (captureState is AutoCaptureState.Locked) {
                        LockBoxOverlay()
                    }
                }

                CameraPermissionState.Checking -> {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(24.dp),
                    ) {
                        Text(
                            "Camera permission required",
                            color      = Color.White,
                            fontSize   = 16.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(Modifier.height(12.dp))
                        Button(onClick = { permLauncher.launch(Manifest.permission.CAMERA) }) {
                            Text("Grant Camera Permission")
                        }
                    }
                }

                CameraPermissionState.Denied -> {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(24.dp),
                    ) {
                        Text(
                            "Camera permission denied",
                            color      = Color(0xFFEF5350),
                            fontSize   = 16.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "Manual capture unavailable until camera permission is granted",
                            color    = Color.White,
                            fontSize = 13.sp,
                        )
                    }
                }
            }
        }

        // ── Right 1/4: task info + state + buttons ──────────────────────────────────────────────
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight()
                .background(MaterialTheme.colorScheme.surface)
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("SKU", fontWeight = FontWeight.Bold, fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(task.sku.itemNumber, fontWeight = FontWeight.Bold)
            Text(task.sku.name, fontSize = 12.sp)
            Text("Resolved: ${task.resolvedBy.name}", fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                if (task.confirmedByUser) "Confirmed by user" else "Not confirmed",
                fontSize = 11.sp,
                color = if (task.confirmedByUser) Color(0xFF2E7D32) else Color(0xFFB71C1C),
            )

            Divider()

            Text("Runtime", fontWeight = FontWeight.Bold, fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                when (runtimeState) {
                    is MnnRuntimeState.Ready    -> "Ready"
                    is MnnRuntimeState.Loading  -> "MNN loading…"
                    is MnnRuntimeState.NotReady -> "Not ready"
                },
                fontSize = 12.sp,
            )

            Divider()

            Text("Capture state", fontWeight = FontWeight.Bold, fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(captureStateLabel(captureState), fontSize = 12.sp)

            captureError?.let { err ->
                Text(
                    "Capture failed: $err",
                    color    = MaterialTheme.colorScheme.error,
                    fontSize = 12.sp,
                )
            }

            Spacer(Modifier.weight(1f))

            // Manual Capture: requires both camera permission and CameraX ready signal.
            Button(
                onClick = {
                    scope.launch {
                        captureError = null
                        runCatching { cameraXController.captureStill() }
                            .onSuccess { photo ->
                                val result = inspectionCoordinator?.inspect(task, photo)
                                    ?: PadInspectionResult(
                                        overallResult      = "MNN_PENDING",
                                        reason             = "Inspection coordinator not available",
                                        modelName          = "Qwen3-VL-2B-Instruct-MNN",
                                        localOnly          = true,
                                        cloudInferenceUsed = false,
                                        capturedImagePath  = photo.rawImagePath,
                                    )
                                onInspectionResult(result)
                            }
                            .onFailure { e ->
                                captureError = e.message ?: "Capture failed"
                            }
                    }
                },
                enabled  = isCameraReady && cameraPermState == CameraPermissionState.Granted,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Manual Capture") }

            OutlinedButton(
                onClick  = { autoCaptureController.onCameraStreaming() },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Reset / Retake") }

            TextButton(
                onClick  = onBack,
                modifier = Modifier.fillMaxWidth(),
            ) { Text("Back to Task Selection") }
        }
    }
}

@Composable
private fun LockBoxOverlay() {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(8.dp)
            .border(3.dp, Color(0xFF00E676))
    )
}

private fun captureStateLabel(state: AutoCaptureState): String = when (state) {
    is AutoCaptureState.Idle              -> "Waiting for camera"
    is AutoCaptureState.Searching         -> "Searching target"
    is AutoCaptureState.CandidateDetected -> "Candidate detected"
    is AutoCaptureState.Locking           -> "Locking…"
    is AutoCaptureState.Locked            -> "Locked"
    is AutoCaptureState.Capturing         -> "Capturing…"
    is AutoCaptureState.Captured          -> "Captured"
    is AutoCaptureState.Rejected          -> when (state.reason) {
        RejectReason.LOCKING_TIMEOUT  -> "Locking timeout"
        RejectReason.CAPTURE_IO_ERROR -> "Capture IO error"
    }
}

/**
 * Computes (width, height) fitting a 4:3 aspect ratio inside the given container.
 * Inputs and outputs are in the same unit (dp values from BoxWithConstraintsScope).
 */
internal fun fitAspect43(containerW: Float, containerH: Float): Pair<Float, Float> {
    val targetAspect = 4f / 3f
    val fromHeight = containerH * targetAspect
    return if (fromHeight <= containerW) Pair(fromHeight, containerH)
    else Pair(containerW, containerW / targetAspect)
}
