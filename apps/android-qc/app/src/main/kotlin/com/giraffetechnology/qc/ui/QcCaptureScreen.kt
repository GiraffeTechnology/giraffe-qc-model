package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Divider
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
 *   ├── Left preview container  (weight=3)
 *   └── Right status panel       (weight=1)
 *
 * 4:3 fit rule (per spec):
 *   previewWidth  = min(containerWidth, containerHeight * 4 / 3)   [in dp]
 *   previewHeight = previewWidth * 3 / 4
 *   then center within container (letterbox/pillarbox remainder)
 *
 * Never fake pass/fail. After capture: MNN pending / review_required.
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
            // maxWidth / maxHeight from BoxWithConstraintsScope are already in Dp
            val containerW = maxWidth.value   // Float, dp units
            val containerH = maxHeight.value  // Float, dp units
            val previewW = minOf(containerW, containerH * 4f / 3f)
            val previewH = previewW * 3f / 4f

            Box(
                modifier = Modifier
                    .size(width = previewW.dp, height = previewH.dp)
                    .background(Color(0xFF1A1A30), RoundedCornerShape(4.dp)),
                contentAlignment = Alignment.Center,
            ) {
                val cameraLabel = when {
                    !cameraConnected -> "Camera: Disconnected"
                    captureState is AutoCaptureState.Captured -> "Captured — MNN pending"
                    else -> "Live Preview (Mock)"
                }
                Text(cameraLabel, color = Color(0xFF444466), fontSize = 13.sp)
            }
        }

        // ── Right: status panel (weight=1) ──
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight()
                .background(Color(0xFF12122A))
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text("GiraffeQC", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            if (skuName.isNotBlank())
                Text(skuName, color = Color(0xFFAAAAAA), fontSize = 11.sp)
            Divider(color = Color(0xFF333355))

            StatusRow(
                "Camera",
                if (cameraConnected) "Connected" else "Disconnected",
                if (cameraConnected) Color(0xFF6BCB77) else Color(0xFFFF6B6B),
            )

            val (targetLabel, targetColor) = targetState(captureState)
            StatusRow("Target", targetLabel, targetColor)

            if (captureState is AutoCaptureState.Locking) {
                StatusRow(
                    "Lock",
                    "${captureState.stableFrameCount}/${captureState.requiredFrameCount}",
                    Color(0xFFFFD93D),
                )
            }

            StatusRow(
                "Capture",
                captureLabel(captureState),
                captureColor(captureState),
            )

            Divider(color = Color(0xFF333355))

            val (mnnLabel, mnnColor) = mnnState(mnnRuntimeState)
            StatusRow("MNN", mnnLabel, mnnColor)

            val resultLabel = when {
                captureState is AutoCaptureState.Captured && mnnRuntimeState !is MnnRuntimeState.Ready ->
                    "MNN pending"
                captureState is AutoCaptureState.Captured ->
                    "review_required"
                else -> "—"
            }
            StatusRow(
                "Result",
                resultLabel,
                if (resultLabel == "—") Color(0xFF888888) else Color(0xFFFFD93D),
            )

            if (operatorId.isNotBlank()) {
                Divider(color = Color(0xFF333355))
                Text("操作员: $operatorId", color = Color(0xFF666688), fontSize = 11.sp)
            }
        }
    }
}

private fun targetState(state: AutoCaptureState): Pair<String, Color> = when (state) {
    AutoCaptureState.Idle               -> "Waiting for camera"  to Color(0xFF888888)
    AutoCaptureState.Searching          -> "Searching target"    to Color(0xFF4ECDC4)
    is AutoCaptureState.CandidateDetected -> "Candidate detected" to Color(0xFFFFD93D)
    is AutoCaptureState.Locking         -> "Locking target"      to Color(0xFFFFD93D)
    is AutoCaptureState.Locked          -> "Target locked"       to Color(0xFF6BCB77)
    is AutoCaptureState.Capturing       -> "Capturing…"         to Color(0xFF4ECDC4)
    is AutoCaptureState.Captured        -> "Captured"            to Color(0xFF6BCB77)
    is AutoCaptureState.Rejected        -> "Rejected"            to Color(0xFFFF6B6B)
}

private fun captureLabel(state: AutoCaptureState): String = when (state) {
    is AutoCaptureState.Captured  -> "Captured"
    is AutoCaptureState.Rejected  -> when (state.reason) {
        RejectReason.LOCKING_TIMEOUT     -> "Rejected: timeout"
        RejectReason.CAPTURE_IO_ERROR    -> "Rejected: IO error"
        RejectReason.CAMERA_DISCONNECTED -> "Rejected: camera lost"
        RejectReason.USER_CANCELLED      -> "Cancelled"
    }
    is AutoCaptureState.Capturing -> "Capturing…"
    else                          -> "Waiting"
}

private fun captureColor(state: AutoCaptureState): Color = when (state) {
    is AutoCaptureState.Captured  -> Color(0xFF6BCB77)
    is AutoCaptureState.Rejected  -> Color(0xFFFF6B6B)
    is AutoCaptureState.Capturing -> Color(0xFF4ECDC4)
    else                          -> Color(0xFF888888)
}

private fun mnnState(state: MnnRuntimeState): Pair<String, Color> = when (state) {
    MnnRuntimeState.Ready    -> "Ready"     to Color(0xFF6BCB77)
    MnnRuntimeState.Loading  -> "Loading…" to Color(0xFF4ECDC4)
    MnnRuntimeState.NotReady -> "Pending"   to Color(0xFFFFD93D)
    is MnnRuntimeState.Error -> "Error"     to Color(0xFFFF6B6B)
}

@Composable
private fun StatusRow(label: String, value: String, dotColor: Color) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, color = Color(0xFFAAAAAA), fontSize = 11.sp, modifier = Modifier.width(52.dp))
        Text(
            value, color = Color.White, fontSize = 11.sp,
            fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f),
        )
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(dotColor, RoundedCornerShape(4.dp)),
        )
    }
}

// ── Previews: verify 4:3 fit at 16:9 and 16:10 container sizes ──────────────────────────

@Preview(name = "QC Capture — 16:9 landscape (1280×720dp)", widthDp = 1280, heightDp = 720)
@Composable
fun PreviewQcCapture_16x9() = QcCaptureScreen(
    captureState    = AutoCaptureState.Searching,
    mnnRuntimeState = MnnRuntimeState.NotReady,
    cameraConnected = true,
    operatorId      = "OP-001",
    skuName         = "Demo SKU",
)

@Preview(name = "QC Capture — 16:10 landscape (1280×800dp)", widthDp = 1280, heightDp = 800)
@Composable
fun PreviewQcCapture_16x10() = QcCaptureScreen(
    captureState    = AutoCaptureState.Locking(stableFrameCount = 5, requiredFrameCount = 10),
    mnnRuntimeState = MnnRuntimeState.NotReady,
    cameraConnected = true,
    operatorId      = "OP-002",
    skuName         = "Demo SKU 16:10",
)

@Preview(name = "QC Capture — Captured state", widthDp = 1280, heightDp = 800)
@Composable
fun PreviewQcCapture_Captured() = QcCaptureScreen(
    captureState    = AutoCaptureState.Captured(
        CapturedPhoto("id-1", "2026-01-01T00:00:00Z", "/tmp/img.jpg", "frame-1", NormalizedBox.DEFAULT)
    ),
    mnnRuntimeState = MnnRuntimeState.NotReady,
    cameraConnected = true,
    operatorId      = "OP-003",
    skuName         = "Demo SKU Captured",
)
