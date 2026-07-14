package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask

@Composable
fun ResultScreen(
    task: QcTask,
    result: PadInspectionResult,
    onRetake: () -> Unit,
    onDone: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Inspection Result", fontSize = 24.sp, fontWeight = FontWeight.Bold)

        // SKU info
        ResultRow("Item number", task.sku.itemNumber)
        ResultRow("SKU name", task.sku.name)

        Divider()

        // Image paths
        result.capturedImagePath?.let { ResultRow("Captured image", it) }

        Divider()

        // Model name
        ResultRow("Model", result.modelName)

        // Overall result banner
        val (label, color) = when (result.overallResult) {
            "ACCEPTED"       -> "ACCEPTED" to Color(0xFF1B5E20)
            "NOT_ACCEPTED"   -> "NOT ACCEPTED" to Color(0xFFB71C1C)
            "MNN_PENDING"    -> "MNN pending" to Color(0xFFF57F17)
            "PENDING_UPLOAD" -> "Pending upload — no verdict" to Color(0xFFF57F17)
            "CLOUD_UNAVAILABLE", "CLOUD_ERROR" -> "Cloud unavailable — no verdict" to Color(0xFFB71C1C)
            else             -> "review_required" to Color(0xFFF57F17)
        }
        Surface(
            color    = color.copy(alpha = 0.15f),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                label,
                modifier   = Modifier.padding(16.dp),
                fontSize   = 22.sp,
                fontWeight = FontWeight.ExtraBold,
                color      = color,
            )
        }

        // Reason
        ResultRow("Reason", result.reason)

        Text(
            if (result.cloudInferenceUsed) "Provider-neutral cloud recognition" else "Explicit legacy local mode",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.weight(1f))

        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            OutlinedButton(onClick = onRetake, modifier = Modifier.weight(1f)) {
                Text("Retake")
            }
            Button(onClick = onDone, modifier = Modifier.weight(1f)) {
                Text("Done")
            }
        }
    }
}

@Composable
private fun ResultRow(label: String, value: String) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment     = Alignment.Top,
    ) {
        Text(
            "$label:",
            fontWeight = FontWeight.SemiBold,
            fontSize   = 13.sp,
            modifier   = Modifier.width(140.dp),
        )
        Text(value, fontSize = 13.sp)
    }
}
