package com.giraffetechnology.qc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask
import com.giraffetechnology.qc.submit.HumanDecision
import com.giraffetechnology.qc.submit.PadOutbox
import com.giraffetechnology.qc.submit.ResultSubmission
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Result review + human decision (S6 §9). The model's recommendation is shown,
 * but the operator makes the binding call (accept / reject / send for review).
 * On decision the result is queued to the Pad outbox carrying the
 * standard_revision_id and bundle_version it ran against, so the Server can
 * recompute against exactly that standard.
 */
@Composable
fun OperatorResultReviewScreen(
    task: QcTask,
    result: PadInspectionResult,
    languageController: LanguageController,
    outbox: PadOutbox,
    onSubmitted: () -> Unit,
    onRetake: () -> Unit,
    now: () -> Long = { System.currentTimeMillis() },
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    // Stable idempotency key for this reviewed result across recompositions.
    val clientJobId = remember(task.sku.id, result.capturedImagePath) { UUID.randomUUID().toString() }
    var submitting by remember { mutableStateOf(false) }

    fun submit(decision: HumanDecision) {
        submitting = true
        scope.launch {
            outbox.enqueue(ResultSubmission.from(task, result, decision, clientJobId, now()))
            onSubmitted()
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row {
            Text(skill.t("pad.review.title"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            LanguageSwitch(languageController)
        }

        Text("${task.sku.itemNumber} — ${task.sku.name}", fontWeight = FontWeight.SemiBold)

        val (label, color) = when (result.overallResult) {
            "ACCEPTED" -> skill.t("verdict.pass") to Color(0xFF1B5E20)
            "NOT_ACCEPTED" -> skill.t("verdict.fail") to Color(0xFFB71C1C)
            else -> skill.t("verdict.review_required") to Color(0xFFF57F17)
        }
        Surface(color = color.copy(alpha = 0.15f), modifier = Modifier.fillMaxWidth()) {
            Text(label, modifier = Modifier.padding(12.dp), fontWeight = FontWeight.ExtraBold, color = color)
        }
        Text(result.reason, fontSize = 13.sp)

        Divider()
        Text(
            skill.t("pad.review.standard_revision", mapOf("rev" to (task.activeStandardRevisionId ?: "—"))),
            fontSize = 12.sp,
        )
        Text(
            skill.t("pad.review.bundle_version", mapOf("ver" to (task.bundleVersion ?: "—"))),
            fontSize = 12.sp,
        )
        Text("${result.modelName}", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)

        Spacer(Modifier.weight(1f))

        // Mandatory human final decision — the model never auto-finalizes.
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            Button(
                onClick = { submit(HumanDecision.PASS) },
                enabled = !submitting,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF1B5E20)),
                modifier = Modifier.weight(1f),
            ) { Text(skill.t("pad.review.confirm_pass")) }
            Button(
                onClick = { submit(HumanDecision.FAIL) },
                enabled = !submitting,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB71C1C)),
                modifier = Modifier.weight(1f),
            ) { Text(skill.t("pad.review.confirm_fail")) }
            OutlinedButton(
                onClick = { submit(HumanDecision.REVIEW_REQUIRED) },
                enabled = !submitting,
                modifier = Modifier.weight(1f),
            ) { Text(skill.t("pad.review.mark_review")) }
        }
        Spacer(Modifier.height(4.dp))
        OutlinedButton(onClick = onRetake, enabled = !submitting, modifier = Modifier.fillMaxWidth()) {
            Text(skill.t("common.retry"))
        }
    }
}
