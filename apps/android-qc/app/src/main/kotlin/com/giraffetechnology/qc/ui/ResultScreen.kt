package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask

@Composable
fun ResultScreen(
    task: QcTask,
    result: PadInspectionResult,
    languageController: LanguageController,
    onRetake: () -> Unit,
    onDone: () -> Unit,
) {
    val skill by languageController.skill.collectAsState()
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skill.t("legacy.result.title"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            LanguageSwitch(languageController)
        }

        // SKU info
        ResultRow(skill.t("legacy.result.item_number"), task.sku.itemNumber)
        ResultRow(skill.t("legacy.result.sku_name"), task.sku.name)

        Divider()

        // Image paths
        result.capturedImagePath?.let { ResultRow(skill.t("legacy.result.captured_image"), it) }

        Divider()

        // Model name
        ResultRow(skill.t("legacy.result.model"), result.modelName)

        // Overall result banner
        val (label, color) = when (result.overallResult) {
            "ACCEPTED"       -> skill.t("verdict.pass") to Color(0xFF1B5E20)
            "NOT_ACCEPTED"   -> skill.t("verdict.fail") to Color(0xFFB71C1C)
            "MNN_PENDING"    -> skill.t("legacy.result.mnn_pending") to Color(0xFFF57F17)
            "PENDING_UPLOAD" -> skill.t("legacy.result.pending_upload") to Color(0xFFF57F17)
            "CLOUD_UNAVAILABLE", "CLOUD_ERROR" ->
                skill.t("legacy.result.cloud_unavailable") to Color(0xFFB71C1C)
            else             -> skill.t("verdict.review_required") to Color(0xFFF57F17)
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
        ResultRow(skill.t("legacy.result.reason"), result.reason)

        Text(
            skill.t(
                if (result.cloudInferenceUsed) "legacy.result.cloud_mode"
                else "legacy.result.local_mode"
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.weight(1f))

        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            OutlinedButton(onClick = onRetake, modifier = Modifier.weight(1f)) {
                Text(skill.t("legacy.result.retake"))
            }
            Button(onClick = onDone, modifier = Modifier.weight(1f)) {
                Text(skill.t("legacy.result.done"))
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
