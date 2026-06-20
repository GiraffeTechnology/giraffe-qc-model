package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Divider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.capture.AutoCaptureState
import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.capture.NormalizedBox
import com.giraffetechnology.qc.capture.RejectReason
import com.giraffetechnology.qc.sku.MnnRuntimeState

/**
 * Main QC capture screen — landscape layout:
 *
 *   Root Row
 *   ├── Left preview container  (weight=3, 4:3 camera preview centered)
 *   └── Right status panel       (weight=1)
 *       ├── reference photo placeholder
 *       ├── detection state
 *       └── MNN / result status
 *
 * 4:3 Fit rule:
 *   previewWidth  = min(containerWidth, containerHeight * 4 / 3)
 *   previewHeight = previewWidth * 3 / 4
 *   then center within container (letterbox/pillarbox remainder)
 *
 * No fake pass/fail. After capture: status = MNN pending / review_required.
 */
@Composable
fun QcCaptureScreen(
    captureState: AutoCaptureState,
    mnnRuntimeState: MnnRuntimeState,
    cameraConnected: Boolean,
    operatorId: String = "",
    skuName: String = "",
) {
    Row(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0A0A18)),
    ) {
        // ── Left: 4:3 camera preview area (weight=3) ──
        BoxWithConstraints(
            modifier = Modifier
                .weight(3f)
                .fillMaxHeight()
                .background(Color(0xFF111120)),
            contentAlignment = Alignment.Center,
        ) {
            val containerW = constraints.maxWidth.toFloat()
            val containerH = constraints.maxHeight.toFloat()
            val previewW = minOf(containerW, containerH * 4f / 3f)
            val previewH = previewW * 3f / 4f

            Box(
                modifier = Modifier
                    .size(
                        width  = (previewW / LocalDensity.current.density).dp,
                        height = (previewH / LocalDensity.current.density).dp,
                    )
                    .background(Color(0xFF1A1A30), RoundedCornerShape(4.dp)),
                contentAlignment = Alignment.Center,
            ) {
                val cameraStatusText = when {
                    !cameraConnected -> "Camera: Disconnected"
                    captureState is AutoCaptureState.Captured -> "Captured"
                    else -> "Live Preview"
                }
                Text(
                    cameraStatusText,
                    color = Color(0xFF444466),
                    fontSize = 14.sp,
                )
                // Real CameraX / UVC surface view placed here in hardware integration
            }
        }

        // ── Right: status panel (weight=1) ──
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight()
                .background(Color(0xFF12122A))
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("GiraffeQC", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            if (skuName.isNotBlank())
                Text(skuName, color = Color(0xFFAAAAAA), fontSize = 12.sp)
            Divider(color = Color(0xFF333355))

            // Camera
            StatusRow(
                label = "Camera",
                value = if (cameraConnected) "Connected" else "Disconnected",
                dotColor = if (cameraConnected) Color(0xFF6BCB77) else Color(0xFFFF6B6B),
            )

            // Target detection
            val (targetLabel, targetColor) = when (captureState) {
                AutoCaptureState.Idle              -> "Waiting for camera"  to Color(0xFF888888)
                AutoCaptureState.Searching         -> "Searching target"    to Color(0xFF4ECDC4)
                is AutoCaptureState.CandidateDetected -> "Candidate detected" to Color(0xFFFFD93D)
                is AutoCaptureState.Locking        -> "Locking target"      to Color(0xFFFFD93D)
                is AutoCaptureState.Locked         -> "Target locked"       to Color(0xFF6BCB77)
                is AutoCaptureState.Capturing      -> "Capturing…"         to Color(0xFF4ECDC4)
                is AutoCaptureState.Captured       -> "Captured"            to Color(0xFF6BCB77)
                is AutoCaptureState.Rejected       -> "Rejected"            to Color(0xFFFF6B6B)
            }
            StatusRow(label = "Target", value = targetLabel, dotColor = targetColor)

            // Locking progress
            if (captureState is AutoCaptureState.Locking) {
                val pct = captureState.stableFrameCount.toFloat() / captureState.requiredFrameCount
                StatusRow(
                    label = "Lock",
                    value = "${captureState.stableFrameCount}/${captureState.requiredFrameCount}",
                    dotColor = Color(0xFFFFD93D),
                )
            }

            // Capture status
            val captureLabel = when (captureState) {
                is AutoCaptureState.Captured  -> "Captured"
                is AutoCaptureState.Rejected  -> when (captureState.reason) {
                    RejectReason.LOCKING_TIMEOUT      -> "Rejected: timeout"
                    RejectReason.CAPTURE_IO_ERROR     -> "Rejected: IO error"
                    RejectReason.CAMERA_DISCONNECTED  -> "Rejected: camera lost"
                    RejectReason.USER_CANCELLED       -> "Cancelled"
                }
                is AutoCaptureState.Capturing -> "Capturing…"
                else                          -> "Waiting"
            }
            StatusRow(
                label = "Capture",
                value = captureLabel,
                dotColor = when (captureState) {
                    is AutoCaptureState.Captured  -> Color(0xFF6BCB77)
                    is AutoCaptureState.Rejected  -> Color(0xFFFF6B6B)
                    is AutoCaptureState.Capturing -> Color(0xFF4ECDC4)
                    else                          -> Color(0xFF888888)
                },
            )

            Divider(color = Color(0xFF333355))

            // MNN runtime
            val (mnnLabel, mnnColor) = when (mnnRuntimeState) {
                MnnRuntimeState.Ready    -> "MNN: Ready"       to Color(0xFF6BCB77)
                MnnRuntimeState.Loading  -> "MNN: Loading…"   to Color(0xFF4ECDC4)
                MnnRuntimeState.NotReady -> "MNN: Pending"     to Color(0xFFFFD93D)
                is MnnRuntimeState.Error -> "MNN: Error"       to Color(0xFFFF6B6B)
            }
            StatusRow(label = "MNN", value = mnnLabel.removePrefix("MNN: "), dotColor = mnnColor)

            // Result: never fake pass/fail; always review_required until real MNN runs
            val resultLabel = when {
                captureState is AutoCaptureState.Captured && mnnRuntimeState !is MnnRuntimeState.Ready ->
                    "MNN pending"
                captureState is AutoCaptureState.Captured ->
                    "review_required"
                else -> "—"
            }
            val resultColor = when {
                resultLabel == "MNN pending"       -> Color(0xFFFFD93D)
                resultLabel == "review_required"   -> Color(0xFFFFD93D)
                else                               -> Color(0xFF888888)
            }
            StatusRow(label = "Result", value = resultLabel, dotColor = resultColor)

            if (operatorId.isNotBlank()) {
                Divider(color = Color(0xFF333355))
                Text("操作员: $operatorId", color = Color(0xFF666688), fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun StatusRow(label: String, value: String, dotColor: Color) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = Color(0xFFAAAAAA), fontSize = 12.sp, modifier = Modifier.width(56.dp))
        Text(
            value, color = Color.White, fontSize = 12.sp,
            fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f),
        )
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(dotColor, RoundedCornerShape(4.dp)),
        )
    }
}

// Import alias to avoid clash with Compose LocalDensity
private val LocalDensity @Composable get() = androidx.compose.ui.platform.LocalDensity.current

// ── Compose Previews (4:3 fit rule checks) ──────────────────────────────────────

@Preview(name = "16:9 landscape (1280×720)", widthDp = 1280, heightDp = 720)
@Composable
fun PreviewQcCapture_16x9() {
    QcCaptureScreen(
        captureState    = AutoCaptureState.Searching,
        mnnRuntimeState = MnnRuntimeState.NotReady,
        cameraConnected = true,
        operatorId      = "OP-001",
        skuName         = "Sample SKU",
    )
}

@Preview(name = "16:10 landscape (1280×800)", widthDp = 1280, heightDp = 800)
@Composable
fun PreviewQcCapture_16x10() {
    QcCaptureScreen(
        captureState    = AutoCaptureState.Locking(stableFrameCount = 5, requiredFrameCount = 10),
        mnnRuntimeState = MnnRuntimeState.NotReady,
        cameraConnected = true,
        operatorId      = "OP-002",
        skuName         = "Another SKU",
    )
}
