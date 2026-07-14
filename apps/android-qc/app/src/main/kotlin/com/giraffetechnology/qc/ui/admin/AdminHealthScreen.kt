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
                "Operator readiness: ${snapshot.operatorPipelineReadiness}",
                fontWeight = FontWeight.SemiBold,
                fontSize = 13.sp,
            )
            Spacer(Modifier.weight(1f))
            Text("Observed: ${snapshot.observedAt}", fontSize = 11.sp)
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
            HealthPanel("Operator Nano CV", Modifier.weight(1f)) {
                KeyValueRow("Status", snapshot.nanoCv.status)
                KeyValueRow("Agent", snapshot.nanoCv.agentVersion ?: "unknown")
                KeyValueRow("Pipeline", snapshot.nanoCv.pipelineVersion ?: "unknown")
                KeyValueRow(
                    "Last real CV",
                    snapshot.nanoCv.lastCvDurationMs?.let { "$it ms" } ?: "unknown",
                )
                KeyValueRow("Last success", snapshot.nanoCv.lastSuccessAt ?: "unknown")
                KeyValueRow("Last error", snapshot.nanoCv.lastErrorCode ?: "none / unknown")
            }

            HealthPanel("Cloud connection", Modifier.weight(1.2f)) {
                KeyValueRow("Link", snapshot.cloudLink.state)
                KeyValueRow("Cloud service", snapshot.cloudLink.cloudService)
                KeyValueRow("Accepting jobs", snapshot.cloudLink.acceptingJobs.toString())
                KeyValueRow("Current network", snapshot.cloudLink.currentNetwork)
                KeyValueRow("Active-job network", snapshot.cloudLink.activeJobNetwork ?: "none")
                KeyValueRow(
                    "Deferred switch",
                    snapshot.cloudLink.switchDeferredUntilJobEnd.toString(),
                )
                KeyValueRow(
                    "Uplink",
                    snapshot.cloudLink.effectiveUplinkMbps?.let { "%.1f Mbps".format(it) }
                        ?: "unknown (min %.1f)".format(snapshot.cloudLink.thresholds.minUplinkMbps),
                )
                KeyValueRow(
                    "RTT",
                    snapshot.cloudLink.rttMs?.let { "$it ms" }
                        ?: "unknown (max ${snapshot.cloudLink.thresholds.maxRttMs})",
                )
                KeyValueRow(
                    "Packet loss",
                    snapshot.cloudLink.packetLossPercent?.let { "%.1f%%".format(it) }
                        ?: "unknown (max %.1f%%)".format(
                            snapshot.cloudLink.thresholds.maxPacketLossPercent
                        ),
                )
                KeyValueRow(
                    "Threshold breaches",
                    snapshot.cloudLink.thresholdBreaches.joinToString().ifEmpty { "none / unknown" },
                )
                KeyValueRow("Last switch", snapshot.cloudLink.lastSwitchSummary ?: "none / unknown")
                KeyValueRow(
                    "Pending uploads",
                    snapshot.offlineQueue.pendingUploadJobs?.toString() ?: "unknown",
                )
            }

            HealthPanel("Administrator Xavier MNN", Modifier.weight(1f)) {
                KeyValueRow("Status", snapshot.xavierAdmin.status)
                KeyValueRow("Runner", snapshot.xavierAdmin.runnerId ?: "not configured")
                KeyValueRow("Engine", snapshot.xavierAdmin.runtimeEngine ?: "unknown")
                KeyValueRow("Adapter", snapshot.xavierAdmin.adapterMode ?: "unknown")
                KeyValueRow("Configured model", snapshot.xavierAdmin.modelName ?: "unknown")
                KeyValueRow(
                    "Model loaded",
                    snapshot.xavierAdmin.modelLoaded?.toString() ?: "unknown",
                )
                KeyValueRow(
                    "Temperature",
                    snapshot.xavierAdmin.temperatureC?.let { "%.1f °C".format(it) }
                        ?: "unknown",
                )
                KeyValueRow("Thermal", snapshot.xavierAdmin.thermalState)
                KeyValueRow(
                    "Disk free",
                    snapshot.xavierAdmin.diskFreeBytes?.let { "%.1f GB".format(it / 1e9) }
                        ?: "unknown",
                )
                KeyValueRow(
                    "Last real recognition",
                    snapshot.xavierAdmin.lastRecognitionLatencyMs?.let { "$it ms" } ?: "unknown",
                )
                KeyValueRow(
                    "Hardware validation",
                    snapshot.xavierAdmin.hardwareValidationStatus,
                )
                if (snapshot.xavierAdmin.mock) {
                    AdminErrorBanner("MOCK INFERENCE — NOT REAL QC JUDGMENT")
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
