package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.capture.*
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.sku.*
import kotlinx.coroutines.launch

/**
 * QC Capture screen — landscape Pad layout.
 *
 * Left 3/4  = camera / capture region (strict 4:3 preview container, centred, no stretch).
 * Right 1/4 = SKU info + auto-capture state + action buttons.
 *
 * Qwen3-VL must NOT run on live frames. Only a captured still image is passed to inspection.
 */
@Composable
fun QcCaptureScreen(
    task: QcTask,
    autoCaptureController: AutoCaptureController,
    runtimeLoader: MnnRuntimeLoader,
    inspectionCoordinator: PadInspectionCoordinator? = null,
    onInspectionResult: (PadInspectionResult) -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val captureState by autoCaptureController.state.collectAsState()
    val runtimeState by runtimeLoader.runtimeState.collectAsState()

    // When AutoCapture produces a photo, run inspection.
    LaunchedEffect(captureState) {
        if (captureState is AutoCaptureState.Captured) {
            val photo = (captureState as AutoCaptureState.Captured).capture
            val result = inspectionCoordinator?.inspect(task, photo)
                ?: PadInspectionResult(
                    overallResult     = "MNN_PENDING",
                    reason            = "Inspection coordinator not available",
                    modelName         = "Qwen3-VL-2B-Instruct-MNN",
                    localOnly         = true,
                    cloudInferenceUsed = false,
                    capturedImagePath = photo.rawImagePath,
                )
            onInspectionResult(result)
        }
    }

    Row(modifier = Modifier.fillMaxSize()) {
        // ── Left 3/4: camera / capture region ─────────────────────────────────
        Box(
            modifier = Modifier
                .weight(3f)
                .fillMaxHeight()
                .background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            // Strict 4:3 preview container centred in the left region.
            // Camera source is CameraUnavailableFrameSource until CameraX is wired.
            BoxWithConstraints(contentAlignment = Alignment.Center) {
                val maxW = constraints.maxWidth.toFloat()
                val maxH = constraints.maxHeight.toFloat()
                val (previewW, previewH) = fitAspect43(maxW, maxH)
                Box(
                    modifier = Modifier
                        .size(width = previewW.dp, height = previewH.dp)
                        .border(2.dp, Color.DarkGray)
                        .background(Color(0xFF1A1A1A)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        "Camera unavailable",
                        color    = Color.Gray,
                        fontSize = 14.sp,
                    )
                }
            }

            // Lock-box overlay when detector has a target.
            if (captureState is AutoCaptureState.Locked) {
                val box = (captureState as AutoCaptureState.Locked).box
                LockBoxOverlay(box)
            }
        }

        // ── Right 1/4: task info + state + buttons ─────────────────────────────
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

            // Runtime state
            Text("Runtime", fontWeight = FontWeight.Bold, fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                when (runtimeState) {
                    is com.giraffetechnology.qc.sku.MnnRuntimeState.Ready    -> "Ready"
                    is com.giraffetechnology.qc.sku.MnnRuntimeState.Loading  -> "MNN loading…"
                    is com.giraffetechnology.qc.sku.MnnRuntimeState.NotReady -> "Not ready"
                },
                fontSize = 12.sp,
            )

            Divider()

            // Auto-capture state
            Text("Capture state", fontWeight = FontWeight.Bold, fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(captureStateLabel(captureState), fontSize = 12.sp)

            Spacer(Modifier.weight(1f))

            // Manual capture button — only enabled when camera source provides a frame.
            // Camera is unavailable in this scaffold; button is shown but disabled.
            Button(
                onClick  = { /* wire to real frame capture when CameraX is integrated */ },
                enabled  = false,
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
private fun LockBoxOverlay(box: NormalizedBox) {
    // Rendered as a fixed-size Box overlay; real coordinate mapping requires
    // the preview pixel dimensions to be passed in. This shows a visual cue.
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(8.dp)
            .border(3.dp, Color(0xFF00E676))
    )
}

private fun captureStateLabel(state: AutoCaptureState): String = when (state) {
    is AutoCaptureState.Idle             -> "Waiting for camera"
    is AutoCaptureState.Searching        -> "Searching target"
    is AutoCaptureState.CandidateDetected -> "Candidate detected"
    is AutoCaptureState.Locking          -> "Locking…"
    is AutoCaptureState.Locked           -> "Locked"
    is AutoCaptureState.Capturing        -> "Capturing…"
    is AutoCaptureState.Captured         -> "Captured"
    is AutoCaptureState.Rejected         -> when ((state as AutoCaptureState.Rejected).reason) {
        RejectReason.LOCKING_TIMEOUT -> "Locking timeout"
        RejectReason.CAPTURE_IO_ERROR -> "Capture IO error"
    }
}

/**
 * Computes (width, height) that fits a 4:3 aspect ratio inside the given container.
 * Returns values in logical dp (the constraints are already in px but the result
 * is used with Modifier.size so the caller must ensure units align).
 */
internal fun fitAspect43(containerW: Float, containerH: Float): Pair<Float, Float> {
    val targetAspect = 4f / 3f
    val fromHeight = containerH * targetAspect
    return if (fromHeight <= containerW) {
        fromHeight to containerH
    } else {
        containerW to (containerW / targetAspect)
    }
}
