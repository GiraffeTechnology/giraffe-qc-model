package com.giraffetechnology.qc.ui.admin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminBundleController
import com.giraffetechnology.qc.admin.AdminBundleState
import com.giraffetechnology.qc.admin.AdminWorkstationController
import com.giraffetechnology.qc.admin.AdminWorkstationOpState
import com.giraffetechnology.qc.admin.AdminWorkstationState
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Workstation registration / bundle assignment (WS3 item 7). Registration and
 * assignment are real backend calls; assignment picks from the live bundle
 * list, and each row shows assigned vs installed sync state.
 */
@Composable
fun AdminWorkstationScreen(
    workstationController: AdminWorkstationController,
    bundleController: AdminBundleController,
    languageController: LanguageController,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val workstations by workstationController.workstations.collectAsState()
    val opState by workstationController.opState.collectAsState()
    val bundles by bundleController.bundles.collectAsState()

    var newId by remember { mutableStateOf("") }
    var newName by remember { mutableStateOf("") }
    var newSite by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        scope.launch(Dispatchers.IO) {
            workstationController.refresh()
            bundleController.refresh()
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.workstations.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            // ── Left: registration form ──────────────────────────────────────
            Column(modifier = Modifier.width(320.dp)) {
                Text(skill.t("admin.workstations.register.title"), fontWeight = FontWeight.SemiBold)
                OutlinedTextField(
                    value = newId, onValueChange = { newId = it },
                    label = { Text(skill.t("admin.workstations.register.id")) },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = newName, onValueChange = { newName = it },
                    label = { Text(skill.t("admin.workstations.register.name")) },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = newSite, onValueChange = { newSite = it },
                    label = { Text(skill.t("admin.workstations.register.site")) },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                when (val op = opState) {
                    is AdminWorkstationOpState.Error -> AdminErrorBanner(skill.t(op.message))
                    is AdminWorkstationOpState.Done -> AdminOkBanner(skill.t("admin.workstations.op_done"))
                    is AdminWorkstationOpState.Working -> Text(skill.t("common.loading"), fontSize = 12.sp)
                    else -> {}
                }
                Spacer(Modifier.height(6.dp))
                Button(onClick = {
                    scope.launch(Dispatchers.IO) {
                        workstationController.register(newId, newName, newSite.takeIf { it.isNotBlank() })
                    }
                }) { Text(skill.t("admin.workstations.register.submit")) }
            }

            // ── Right: workstation list + assign ─────────────────────────────
            Column(modifier = Modifier.weight(1f)) {
                when (val w = workstations) {
                    is AdminWorkstationState.Loading -> Text(skill.t("common.loading"), fontSize = 13.sp)
                    is AdminWorkstationState.Error -> AdminErrorBanner(skill.t(w.message))
                    is AdminWorkstationState.Loaded -> {
                        if (w.workstations.isEmpty()) {
                            Text(skill.t("admin.workstations.empty"), fontSize = 13.sp)
                        }
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            items(w.workstations) { ws ->
                                var assignMenu by remember(ws.id) { mutableStateOf(false) }
                                Surface(tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
                                    Column(modifier = Modifier.padding(10.dp)) {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text(ws.displayName, fontWeight = FontWeight.SemiBold)
                                            Spacer(Modifier.padding(horizontal = 4.dp))
                                            Text("(${ws.workstationId})", fontSize = 12.sp)
                                            Spacer(Modifier.weight(1f))
                                            if (ws.inSync) {
                                                Text("✓ " + skill.t("admin.workstations.in_sync"), fontSize = 12.sp)
                                            }
                                        }
                                        KeyValueRow(
                                            skill.t("admin.workstations.field.assigned"),
                                            ws.assignedBundleVersion ?: "—",
                                        )
                                        KeyValueRow(
                                            skill.t("admin.workstations.field.installed"),
                                            ws.installedBundleVersion ?: "—",
                                        )
                                        KeyValueRow(
                                            skill.t("admin.workstations.field.last_seen"),
                                            ws.lastSeenAt ?: "—",
                                        )
                                        Spacer(Modifier.height(6.dp))
                                        Column {
                                            OutlinedButton(onClick = { assignMenu = true }) {
                                                Text(skill.t("admin.workstations.assign"))
                                            }
                                            DropdownMenu(
                                                expanded = assignMenu,
                                                onDismissRequest = { assignMenu = false },
                                            ) {
                                                val loaded = bundles as? AdminBundleState.Loaded
                                                if (loaded == null || loaded.bundles.isEmpty()) {
                                                    DropdownMenuItem(
                                                        text = { Text(skill.t("admin.bundles.empty")) },
                                                        onClick = { assignMenu = false },
                                                    )
                                                } else {
                                                    loaded.bundles.forEach { bundle ->
                                                        DropdownMenuItem(
                                                            text = { Text(bundle.bundleVersion) },
                                                            onClick = {
                                                                assignMenu = false
                                                                scope.launch(Dispatchers.IO) {
                                                                    workstationController.assign(ws.id, bundle.id)
                                                                }
                                                            },
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
        }
    }
}
