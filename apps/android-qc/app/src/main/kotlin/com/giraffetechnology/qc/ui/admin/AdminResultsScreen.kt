package com.giraffetechnology.qc.ui.admin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminDecisionState
import com.giraffetechnology.qc.admin.AdminResultsController
import com.giraffetechnology.qc.admin.AdminResultsState
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Server verdict / false-pass incident viewing (WS3 item 10). Lists server
 * verdicts (with pad/server agreement and failing checkpoints) and active
 * suspensions; a review-required verdict can be finalized here, attributed to
 * the logged-in admin.
 */
@Composable
fun AdminResultsScreen(
    controller: AdminResultsController,
    languageController: LanguageController,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val state by controller.state.collectAsState()
    val decision by controller.decision.collectAsState()

    LaunchedEffect(Unit) {
        scope.launch(Dispatchers.IO) { controller.refresh() }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.results.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(12.dp))

        when (val d = decision) {
            is AdminDecisionState.Error -> AdminErrorBanner(d.message)
            is AdminDecisionState.Saved -> AdminOkBanner(skill.t("admin.results.decision_saved"))
            else -> {}
        }

        when (val s = state) {
            is AdminResultsState.Loading -> Text(skill.t("common.loading"), fontSize = 13.sp)
            is AdminResultsState.Error -> AdminErrorBanner(s.message)
            is AdminResultsState.Loaded -> {
                if (s.suspensions.isNotEmpty()) {
                    AdminErrorBanner(
                        skill.t("admin.results.active_suspensions",
                            mapOf("count" to s.suspensions.size.toString()))
                    )
                    Spacer(Modifier.height(8.dp))
                }
                if (s.verdicts.isEmpty()) {
                    Text(skill.t("admin.results.empty"), fontSize = 13.sp)
                }
                LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(s.verdicts) { v ->
                        var comment by remember(v.submissionId) { mutableStateOf("") }
                        Surface(tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.padding(10.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(v.submissionId.take(12) + "…", fontWeight = FontWeight.SemiBold)
                                    Spacer(Modifier.weight(1f))
                                    Text(
                                        v.serverOverallResult.uppercase(),
                                        color = when (v.serverOverallResult) {
                                            "pass" -> Color(0xFF2E7D32)
                                            "fail" -> Color(0xFFB71C1C)
                                            else -> Color(0xFFB26A00)
                                        },
                                        fontWeight = FontWeight.Bold,
                                    )
                                }
                                KeyValueRow(
                                    skill.t("admin.results.field.pad_vs_server"),
                                    "${v.padOverallResult} / ${v.serverOverallResult}" +
                                        if (v.agrees) " ✓" else " ✗",
                                )
                                if (v.failingCheckpoints.isNotEmpty()) {
                                    KeyValueRow(
                                        skill.t("admin.results.field.failing"),
                                        v.failingCheckpoints.joinToString(", "),
                                    )
                                }
                                KeyValueRow(
                                    skill.t("admin.results.field.bundle"),
                                    v.bundleVersion ?: "—",
                                )
                                v.humanFinalDecision?.let {
                                    KeyValueRow(skill.t("admin.results.field.final"), it)
                                }
                                if (v.reviewRequired && v.humanFinalDecision == null) {
                                    Spacer(Modifier.height(6.dp))
                                    Text(
                                        skill.t("admin.results.review_required"),
                                        fontSize = 12.sp,
                                        color = Color(0xFFB26A00),
                                        fontWeight = FontWeight.SemiBold,
                                    )
                                    OutlinedTextField(
                                        value = comment,
                                        onValueChange = { comment = it },
                                        label = { Text(skill.t("admin.results.comment")) },
                                        singleLine = true,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                    Spacer(Modifier.height(4.dp))
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(onClick = {
                                            scope.launch(Dispatchers.IO) {
                                                controller.recordDecision(v.submissionId, "pass", comment)
                                            }
                                        }) { Text(skill.t("verdict.pass")) }
                                        OutlinedButton(onClick = {
                                            scope.launch(Dispatchers.IO) {
                                                controller.recordDecision(v.submissionId, "fail", comment)
                                            }
                                        }) { Text(skill.t("verdict.fail")) }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
