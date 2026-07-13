package com.giraffetechnology.qc.ui.admin

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import com.giraffetechnology.qc.admin.AdminProbationController
import com.giraffetechnology.qc.admin.AdminProbationState
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Probation / qualification management (WS3 item 9). Active suspensions come
 * from the live suspensions API; the probation gate / agreement / pause-resume
 * panel is built against WS7's pending contract and states that explicitly —
 * only the network call is stubbed, never the UI.
 */
@Composable
fun AdminProbationScreen(
    controller: AdminProbationController,
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
            title = skill.t("admin.probation.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(12.dp))

        when (val s = state) {
            is AdminProbationState.Loading -> Text(skill.t("common.loading"), fontSize = 13.sp)
            is AdminProbationState.Error -> AdminErrorBanner(s.message)
            is AdminProbationState.Loaded -> {
                Text(
                    skill.t("admin.probation.suspensions"),
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 15.sp,
                )
                Spacer(Modifier.height(6.dp))
                if (s.suspensions.isEmpty()) {
                    Text(skill.t("admin.probation.no_suspensions"), fontSize = 13.sp)
                } else {
                    LazyColumn(
                        modifier = Modifier.weight(1f, fill = false),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        items(s.suspensions) { susp ->
                            Surface(tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
                                Column(modifier = Modifier.padding(10.dp)) {
                                    Text(susp.id, fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                                    KeyValueRow(
                                        skill.t("admin.probation.field.pack"),
                                        susp.trainingPackId ?: "—",
                                    )
                                    KeyValueRow(skill.t("admin.probation.field.status"), susp.status)
                                    KeyValueRow(
                                        skill.t("admin.probation.field.reason"),
                                        susp.reason ?: "—",
                                    )
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(14.dp))

                Text(
                    skill.t("admin.probation.gate"),
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 15.sp,
                )
                Spacer(Modifier.height(6.dp))
                if (s.probationBackendPending.isNotEmpty()) {
                    BackendPendingBanner(skill.t("admin.probation.pending"))
                }
            }
        }
    }
}
