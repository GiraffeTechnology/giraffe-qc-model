package com.giraffetechnology.qc.ui.admin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminHealthController
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Architecture v2 health: Operator Nano CV, Operator cloud/link, and the
 * Administrator Xavier MNN node are deliberately separate. Xavier readiness
 * never implies the Operator can start a live cloud job.
 */
@Composable
fun AdminHealthScreen(
    controller: AdminHealthController,
    languageController: LanguageController,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val state by controller.state.collectAsState()
    val snapshot = state.snapshot

    LaunchedEffect(Unit) {
        scope.launch(Dispatchers.IO) { controller.refresh() }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.health.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(8.dp))
        Row(modifier = Modifier.fillMaxWidth()) {
            Text(
                skill.t(
                    "admin.health.operator_readiness",
                    mapOf("status" to snapshot.operatorPipelineReadiness),
                ),
                fontWeight = FontWeight.SemiBold,
                fontSize = 13.sp,
            )
            Spacer(Modifier.weight(1f))
            Text(
                skill.t("admin.health.observed", mapOf("time" to snapshot.observedAt)),
                fontSize = 11.sp,
            )
            Spacer(Modifier.padding(horizontal = 4.dp))
            OutlinedButton(
                enabled = !state.refreshing,
                onClick = { scope.launch(Dispatchers.IO) { controller.refresh() } },
            ) { Text(skill.t("common.retry")) }
        }
        state.error?.let { AdminErrorBanner(it) }
        snapshot.limitations.forEach { BackendPendingBanner(it) }
        Spacer(Modifier.height(8.dp))

        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            val unknown = skill.t("common.unknown")
            val noneUnknown = skill.t("admin.health.value.none_unknown")
            HealthPanel(skill.t("admin.health.nano_cv"), Modifier.weight(1f)) {
                KeyValueRow(skill.t("admin.health.field.status"), snapshot.nanoCv.status)
                KeyValueRow(skill.t("admin.health.field.agent"), snapshot.nanoCv.agentVersion ?: unknown)
                KeyValueRow(skill.t("admin.health.field.pipeline"), snapshot.nanoCv.pipelineVersion ?: unknown)
                KeyValueRow(
                    skill.t("admin.health.field.last_real_cv"),
                    snapshot.nanoCv.lastCvDurationMs?.let { "$it ms" } ?: unknown,
                )
                KeyValueRow(skill.t("admin.health.field.last_success"), snapshot.nanoCv.lastSuccessAt ?: unknown)
                KeyValueRow(skill.t("admin.health.field.last_error"), snapshot.nanoCv.lastErrorCode ?: noneUnknown)
            }

            HealthPanel(skill.t("admin.health.cloud_connection"), Modifier.weight(1.2f)) {
                KeyValueRow(skill.t("admin.health.field.link"), snapshot.cloudLink.state)
                KeyValueRow(skill.t("admin.health.field.cloud_service"), snapshot.cloudLink.cloudService)
                KeyValueRow(
                    skill.t("admin.health.field.accepting_jobs"),
                    skill.t(if (snapshot.cloudLink.acceptingJobs) "common.yes" else "common.no"),
                )
                KeyValueRow(skill.t("admin.health.field.current_network"), snapshot.cloudLink.currentNetwork)
                KeyValueRow(
                    skill.t("admin.health.field.active_job_network"),
                    snapshot.cloudLink.activeJobNetwork ?: skill.t("admin.health.value.none"),
                )
                KeyValueRow(
                    skill.t("admin.health.field.deferred_switch"),
                    skill.t(if (snapshot.cloudLink.switchDeferredUntilJobEnd) "common.yes" else "common.no"),
                )
                KeyValueRow(
                    skill.t("admin.health.field.uplink"),
                    snapshot.cloudLink.effectiveUplinkMbps?.let { "%.1f Mbps".format(it) }
                        ?: skill.t(
                            "admin.health.value.unknown_min",
                            mapOf("value" to "%.1f Mbps".format(snapshot.cloudLink.thresholds.minUplinkMbps)),
                        ),
                )
                KeyValueRow(
                    skill.t("admin.health.field.rtt"),
                    snapshot.cloudLink.rttMs?.let { "$it ms" }
                        ?: skill.t(
                            "admin.health.value.unknown_max",
                            mapOf("value" to "${snapshot.cloudLink.thresholds.maxRttMs} ms"),
                        ),
                )
                KeyValueRow(
                    skill.t("admin.health.field.packet_loss"),
                    snapshot.cloudLink.packetLossPercent?.let { "%.1f%%".format(it) }
                        ?: skill.t(
                            "admin.health.value.unknown_max",
                            mapOf(
                                "value" to "%.1f%%".format(
                                    snapshot.cloudLink.thresholds.maxPacketLossPercent
                                )
                            ),
                        ),
                )
                KeyValueRow(
                    skill.t("admin.health.field.threshold_breaches"),
                    snapshot.cloudLink.thresholdBreaches.joinToString().ifEmpty { noneUnknown },
                )
                KeyValueRow(
                    skill.t("admin.health.field.last_switch"),
                    snapshot.cloudLink.lastSwitchSummary ?: noneUnknown,
                )
                KeyValueRow(
                    skill.t("admin.health.field.pending_uploads"),
                    snapshot.offlineQueue.pendingUploadJobs?.toString() ?: unknown,
                )
            }

            HealthPanel(skill.t("admin.health.xavier_admin"), Modifier.weight(1f)) {
                KeyValueRow(skill.t("admin.health.field.status"), snapshot.xavierAdmin.status)
                KeyValueRow(
                    skill.t("admin.health.field.runner"),
                    snapshot.xavierAdmin.runnerId ?: skill.t("admin.health.value.not_configured"),
                )
                KeyValueRow(skill.t("admin.health.field.engine"), snapshot.xavierAdmin.runtimeEngine ?: unknown)
                KeyValueRow(skill.t("admin.health.field.adapter"), snapshot.xavierAdmin.adapterMode ?: unknown)
                KeyValueRow(skill.t("admin.health.field.configured_model"), snapshot.xavierAdmin.modelName ?: unknown)
                KeyValueRow(
                    skill.t("admin.health.field.model_loaded"),
                    snapshot.xavierAdmin.modelLoaded?.let {
                        skill.t(if (it) "common.yes" else "common.no")
                    } ?: unknown,
                )
                KeyValueRow(
                    skill.t("admin.health.field.temperature"),
                    snapshot.xavierAdmin.temperatureC?.let { "%.1f °C".format(it) }
                        ?: unknown,
                )
                KeyValueRow(skill.t("admin.health.field.thermal"), snapshot.xavierAdmin.thermalState)
                KeyValueRow(
                    skill.t("admin.health.field.disk_free"),
                    snapshot.xavierAdmin.diskFreeBytes?.let { "%.1f GB".format(it / 1e9) }
                        ?: unknown,
                )
                KeyValueRow(
                    skill.t("admin.health.field.last_recognition"),
                    snapshot.xavierAdmin.lastRecognitionLatencyMs?.let { "$it ms" } ?: unknown,
                )
                KeyValueRow(
                    skill.t("admin.health.field.hardware_validation"),
                    snapshot.xavierAdmin.hardwareValidationStatus,
                )
                if (snapshot.xavierAdmin.mock) {
                    AdminErrorBanner(skill.t("pad.jetson.health.mock_warning"))
                }
            }
        }
    }
}

@Composable
private fun HealthPanel(title: String, modifier: Modifier, content: @Composable () -> Unit) {
    Surface(tonalElevation = 2.dp, modifier = modifier) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
            Spacer(Modifier.height(6.dp))
            content()
        }
    }
}
