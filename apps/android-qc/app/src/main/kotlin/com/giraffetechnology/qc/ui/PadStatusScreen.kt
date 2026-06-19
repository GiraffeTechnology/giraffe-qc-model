package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Android Pad local-only status screen.
 *
 * Shows operator-facing status for the offline Qwen3-VL-4B MNN inspection engine.
 *
 * MUST NOT show: Qwen API key input, DashScope key, cloud fallback toggle,
 * remote inference settings, or any network-related controls.
 *
 * Operator sees:
 *   Engine: Local Qwen3-VL-4B MNN
 *   Mode: Offline Pad
 *   Cloud: Disabled
 *   Network: Not used
 */
@Composable
fun PadStatusScreen(
    modelReady: Boolean,
    runtimeReady: Boolean,
    inspectionResult: String?,
    isRunning: Boolean,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF1A1A2E))
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text(
            text = "GiraffeQC — Android Pad",
            color = Color.White,
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
        )

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Color(0xFF444466)),
        )

        StatusRow(label = "Engine",  value = "Local Qwen3-VL-4B MNN", dotColor = if (runtimeReady) Color(0xFF6BCB77) else Color(0xFFFF6B6B))
        StatusRow(label = "Mode",    value = "Offline Pad",            dotColor = Color(0xFF6BCB77))
        StatusRow(label = "Cloud",   value = "Disabled",               dotColor = Color(0xFF888888))
        StatusRow(label = "Network", value = "Not used",               dotColor = Color(0xFF888888))

        Spacer(Modifier.height(8.dp))

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(Color(0xFF444466)),
        )

        Spacer(Modifier.height(8.dp))

        val (badgeText, badgeColor) = when {
            !modelReady   -> "Local model not ready" to Color(0xFFFF6B6B)
            !runtimeReady -> "Local runtime not ready" to Color(0xFFFFD93D)
            isRunning     -> "Inspection running locally..." to Color(0xFF4ECDC4)
            inspectionResult == "pass"            -> "Result: PASS" to Color(0xFF6BCB77)
            inspectionResult == "fail"            -> "Result: FAIL" to Color(0xFFFF6B6B)
            inspectionResult == "review_required" -> "Result: REVIEW REQUIRED" to Color(0xFFFFD93D)
            inspectionResult != null              -> "Result: $inspectionResult" to Color.Gray
            else -> "Local model ready — awaiting inspection" to Color(0xFF6BCB77)
        }

        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = badgeColor.copy(alpha = 0.15f),
        ) {
            Text(
                text = badgeText,
                color = badgeColor,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
            )
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
        Text(
            text = label,
            color = Color(0xFFAAAAAA),
            fontSize = 14.sp,
            modifier = Modifier.width(100.dp),
        )
        Text(
            text = value,
            color = Color.White,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.weight(1f),
        )
        Box(
            modifier = Modifier
                .size(10.dp)
                .background(dotColor),
        )
    }
}
