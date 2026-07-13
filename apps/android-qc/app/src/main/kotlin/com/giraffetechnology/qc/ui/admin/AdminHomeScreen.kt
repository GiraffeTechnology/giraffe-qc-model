package com.giraffetechnology.qc.ui.admin

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminLoginController
import com.giraffetechnology.qc.admin.AdminLoginState
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.ui.LanguageSwitch

/** One destination card on the Administrator home grid. */
data class AdminDestination(val titleKey: String, val descKey: String, val onOpen: () -> Unit)

/**
 * Administrator home (replaces the old info-only screen): a card grid over the
 * eight working admin areas, with the logged-in identity always visible.
 */
@Composable
fun AdminHomeScreen(
    loginController: AdminLoginController,
    languageController: LanguageController,
    onOpenSkus: () -> Unit,
    onOpenBundles: () -> Unit,
    onOpenWorkstations: () -> Unit,
    onOpenHealth: () -> Unit,
    onOpenProbation: () -> Unit,
    onOpenResults: () -> Unit,
    onOpenJetsonPairing: () -> Unit,
    onLogout: () -> Unit,
) {
    val skill by languageController.skill.collectAsState()
    val loginState by loginController.state.collectAsState()
    val identity = (loginState as? AdminLoginState.LoggedIn)?.identity

    val destinations = listOf(
        AdminDestination("admin.home.skus", "admin.home.skus.desc", onOpenSkus),
        AdminDestination("admin.home.bundles", "admin.home.bundles.desc", onOpenBundles),
        AdminDestination("admin.home.workstations", "admin.home.workstations.desc", onOpenWorkstations),
        AdminDestination("admin.home.health", "admin.home.health.desc", onOpenHealth),
        AdminDestination("admin.home.probation", "admin.home.probation.desc", onOpenProbation),
        AdminDestination("admin.home.results", "admin.home.results.desc", onOpenResults),
        AdminDestination("admin.home.pairing", "admin.home.pairing.desc", onOpenJetsonPairing),
    )

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skill.t("admin.home.title"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            if (identity != null) {
                Text(
                    "${identity.username} · ${identity.tenantId}",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.padding(horizontal = 6.dp))
            }
            LanguageSwitch(languageController)
            OutlinedButton(onClick = onLogout) { Text(skill.t("admin.home.logout")) }
        }
        Spacer(Modifier.height(12.dp))

        LazyVerticalGrid(
            columns = GridCells.Fixed(3),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            items(destinations) { dest ->
                Surface(
                    tonalElevation = 2.dp,
                    shape = MaterialTheme.shapes.medium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { dest.onOpen() },
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            skill.t(dest.titleKey),
                            fontSize = 17.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            skill.t(dest.descKey),
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}
