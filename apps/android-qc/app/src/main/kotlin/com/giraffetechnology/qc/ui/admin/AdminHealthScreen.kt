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
import com.giraffetechnology.qc.admin.JetsonHealthState
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Pad / Jetson health (WS3 item 8). The Pad panel is fully real (MNN runtime
 * state, disk, build identity). The Jetson panel is wired to the health API
 * call whose contract (WS4/WS5) is not yet published — it renders an explicit
 * backend-pending banner rather than placeholder numbers.
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
        Spacer(Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            // ── Pad health (real, on-device) ─────────────────────────────────
            Surface(tonalElevation = 2.dp, modifier = Modifier.weight(1f)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(skill.t("admin.health.pad"), fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                    Spacer(Modifier.height(8.dp))
                    val pad = state.pad
                    if (pad == null) {
                        Text(skill.t("common.loading"), fontSize = 13.sp)
                    } else {
                        KeyValueRow(
                            skill.t("admin.health.model"),
                            skill.t("admin.health.model.${pad.modelState}"),
                        )
                        KeyValueRow(
                            skill.t("admin.health.disk"),
                            "%.1f / %.1f GB".format(
                                pad.diskFreeBytes / 1e9, pad.diskTotalBytes / 1e9,
                            ),
                        )
                        KeyValueRow(skill.t("admin.health.app_version"), pad.appVersionName)
                        KeyValueRow(skill.t("admin.health.build"), pad.buildProvenance)
                    }
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = {
                        scope.launch(Dispatchers.IO) { controller.refresh() }
                    }) { Text(skill.t("common.retry")) }
                }
            }

            // ── Jetson health (backend-pending, labeled) ─────────────────────
            Surface(tonalElevation = 2.dp, modifier = Modifier.weight(1f)) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(skill.t("admin.health.jetson"), fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
                    Spacer(Modifier.height(8.dp))
                    when (val j = state.jetson) {
                        is JetsonHealthState.Loaded -> KeyValueRow(skill.t("admin.health.model"), j.summary)
                        is JetsonHealthState.Error -> AdminErrorBanner(j.message)
                        is JetsonHealthState.BackendPending ->
                            BackendPendingBanner(skill.t("admin.health.jetson.pending"))
                    }
                }
            }
        }
    }
}
