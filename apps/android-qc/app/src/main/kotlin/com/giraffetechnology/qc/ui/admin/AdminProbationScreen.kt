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
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminProbationController
import com.giraffetechnology.qc.admin.AdminProbationMutationState
import com.giraffetechnology.qc.admin.AdminProbationState
import com.giraffetechnology.qc.admin.probationActionPolicy
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** Live probation state/actions from docs/api-contracts/probation-api.md. */
@Composable
fun AdminProbationScreen(
    controller: AdminProbationController,
    languageController: LanguageController,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val state by controller.state.collectAsState()
    val mutation by controller.mutation.collectAsState()
    var revisionId by remember { mutableStateOf("") }

    LaunchedEffect(Unit) { scope.launch(Dispatchers.IO) { controller.refresh(null) } }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.probation.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = revisionId,
                onValueChange = { revisionId = it },
                label = { Text(skill.t("admin.probation.revision_id")) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Button(
                enabled = revisionId.isNotBlank() && mutation !is AdminProbationMutationState.Working,
                onClick = { scope.launch(Dispatchers.IO) { controller.refresh(revisionId) } },
            ) { Text(skill.t("common.load")) }
        }
        if (mutation is AdminProbationMutationState.Working) {
            Text(skill.t("admin.probation.updating"), fontSize = 12.sp)
        }
        (mutation as? AdminProbationMutationState.Error)?.let { AdminErrorBanner(it.message) }
        Spacer(Modifier.height(10.dp))

        when (val current = state) {
            is AdminProbationState.Loading -> Text(skill.t("common.loading"), fontSize = 13.sp)
            is AdminProbationState.Error -> AdminErrorBanner(current.message)
            is AdminProbationState.Loaded -> Row(
                modifier = Modifier.fillMaxSize(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Surface(tonalElevation = 2.dp, modifier = Modifier.weight(1f)) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(skill.t("admin.probation.gate"), fontWeight = FontWeight.SemiBold)
                        Spacer(Modifier.height(6.dp))
                        current.notice?.let { Text(it, fontSize = 13.sp) }
                        current.probation?.let { probation ->
                            val actions = probationActionPolicy(probation.status)
                            KeyValueRow(skill.t("admin.probation.field.status"), probation.status)
                            KeyValueRow(skill.t("admin.probation.field.sku"), probation.skuId)
                            KeyValueRow(skill.t("admin.probation.field.revision"), probation.standardRevisionId)
                            KeyValueRow(
                                skill.t("admin.probation.field.jobs"),
                                "${probation.gate.jobsRecorded} / ${probation.gate.minSampleSize}",
                            )
                            KeyValueRow(
                                skill.t("admin.probation.field.agreements"),
                                probation.gate.agreements.toString(),
                            )
                            KeyValueRow(
                                skill.t("admin.probation.field.agreement_rate"),
                                skill.t(
                                    "admin.probation.rate_threshold",
                                    mapOf(
                                        "rate" to "%.1f".format(probation.gate.agreementRate * 100),
                                        "threshold" to "%.1f".format(
                                            probation.gate.agreementThreshold * 100
                                        ),
                                    ),
                                ),
                            )
                            KeyValueRow(
                                skill.t("admin.probation.field.next_cadence"),
                                skill.t(
                                    "admin.probation.every_jobs",
                                    mapOf("count" to probation.gate.recheckInterval.toString()),
                                ),
                            )
                            KeyValueRow(
                                skill.t("admin.probation.field.check_due"),
                                skill.t(if (probation.gate.checkDue) "common.yes" else "common.no"),
                            )
                            KeyValueRow(
                                skill.t("admin.probation.field.qualified"),
                                skill.t(if (probation.gate.qualified) "common.yes" else "common.no"),
                            )
                            KeyValueRow(
                                skill.t("admin.probation.field.human_required"),
                                skill.t(
                                    if (actions.humanFinalVerdictRequired) "common.yes"
                                    else "common.no"
                                ),
                            )
                            Spacer(Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                if (actions.canPause) {
                                    OutlinedButton(
                                        enabled = mutation !is AdminProbationMutationState.Working,
                                        onClick = { scope.launch(Dispatchers.IO) { controller.pause() } },
                                    ) { Text(skill.t("admin.probation.pause")) }
                                }
                                if (actions.canResume) {
                                    OutlinedButton(
                                        enabled = mutation !is AdminProbationMutationState.Working,
                                        onClick = { scope.launch(Dispatchers.IO) { controller.resume() } },
                                    ) { Text(skill.t("admin.probation.resume")) }
                                }
                                OutlinedButton(
                                    enabled = actions.canViewReport &&
                                        mutation !is AdminProbationMutationState.Working,
                                    onClick = {
                                        scope.launch(Dispatchers.IO) { controller.loadDisagreementReport() }
                                    },
                                ) { Text(skill.t("admin.probation.view_disagreements")) }
                            }
                        }
                        current.report?.let { report ->
                            Spacer(Modifier.height(10.dp))
                            Text(skill.t("admin.probation.report"), fontWeight = FontWeight.SemiBold)
                            KeyValueRow(
                                skill.t("admin.probation.disagreeing_jobs"),
                                report.disagreements.toString(),
                            )
                            report.detectionPoints.forEach { point ->
                                KeyValueRow(point.pointCode, point.disagreementCount.toString())
                            }
                            report.jobs.take(10).forEach { job ->
                                Text(
                                    skill.t(
                                        "admin.probation.job_line",
                                        mapOf(
                                            "sequence" to job.sequenceNo.toString(),
                                            "job" to job.jobRef,
                                            "ai" to job.aiVerdict,
                                            "human" to job.humanFinalVerdict,
                                        ),
                                    ),
                                    fontSize = 11.sp,
                                )
                            }
                        }
                    }
                }

                Surface(tonalElevation = 2.dp, modifier = Modifier.weight(0.8f)) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(skill.t("admin.probation.suspensions"), fontWeight = FontWeight.SemiBold)
                        Spacer(Modifier.height(6.dp))
                        if (current.suspensions.isEmpty()) {
                            Text(skill.t("admin.probation.no_suspensions"), fontSize = 13.sp)
                        } else {
                            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                items(current.suspensions) { suspension ->
                                    Surface(tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
                                        Column(modifier = Modifier.padding(8.dp)) {
                                            Text(suspension.id, fontWeight = FontWeight.SemiBold)
                                            KeyValueRow(
                                                skill.t("admin.probation.field.status"),
                                                suspension.status,
                                            )
                                            KeyValueRow(
                                                skill.t("admin.probation.field.reason"),
                                                suspension.reason ?: skill.t("common.unknown"),
                                            )
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
}
