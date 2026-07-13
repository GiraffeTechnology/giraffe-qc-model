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
import com.giraffetechnology.qc.admin.AdminBundleController
import com.giraffetechnology.qc.admin.AdminBundleState
import com.giraffetechnology.qc.admin.AdminPublishState
import com.giraffetechnology.qc.admin.AdminSkuController
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Bundle publish / download status (WS3 item 6). Publish triggers the server's
 * signed-bundle pipeline for the selected SKU; "verify download" fetches the
 * signed bundle through the server's fail-closed verification route and shows
 * the verified manifest hash.
 */
@Composable
fun AdminBundleScreen(
    bundleController: AdminBundleController,
    skuController: AdminSkuController,
    languageController: LanguageController,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val bundles by bundleController.bundles.collectAsState()
    val publish by bundleController.publish.collectAsState()
    val downloadChecks by bundleController.downloadChecks.collectAsState()
    val selectedSku by skuController.selected.collectAsState()

    LaunchedEffect(Unit) {
        scope.launch(Dispatchers.IO) { bundleController.refresh() }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.bundles.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(12.dp))

        val sku = selectedSku
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            if (sku != null) {
                Text(
                    skill.t("admin.bundles.publish_for", mapOf("item" to sku.itemNumber)),
                    fontSize = 14.sp,
                )
                Spacer(Modifier.padding(horizontal = 6.dp))
                Button(
                    enabled = publish !is AdminPublishState.Publishing,
                    onClick = { scope.launch(Dispatchers.IO) { bundleController.publish(sku.id) } },
                ) { Text(skill.t("admin.bundles.publish")) }
            } else {
                Text(skill.t("admin.bundles.no_sku_selected"), fontSize = 13.sp)
            }
            Spacer(Modifier.weight(1f))
            OutlinedButton(onClick = { scope.launch(Dispatchers.IO) { bundleController.refresh() } }) {
                Text(skill.t("common.retry"))
            }
        }
        when (val p = publish) {
            is AdminPublishState.Publishing -> Text(skill.t("common.loading"), fontSize = 12.sp)
            is AdminPublishState.Published -> AdminOkBanner(skill.t("admin.bundles.published"))
            is AdminPublishState.Error -> AdminErrorBanner(p.message)
            else -> {}
        }
        Spacer(Modifier.height(12.dp))

        when (val b = bundles) {
            is AdminBundleState.Loading -> Text(skill.t("common.loading"), fontSize = 13.sp)
            is AdminBundleState.Error -> AdminErrorBanner(b.message)
            is AdminBundleState.Loaded -> {
                if (b.bundles.isEmpty()) Text(skill.t("admin.bundles.empty"), fontSize = 13.sp)
                LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(b.bundles) { bundle ->
                        Surface(tonalElevation = 1.dp, modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.padding(10.dp)) {
                                Text(bundle.bundleVersion, fontWeight = FontWeight.SemiBold)
                                KeyValueRow(skill.t("admin.bundles.field.status"), bundle.status)
                                KeyValueRow(
                                    skill.t("admin.bundles.field.signed"),
                                    if (bundle.signed) "✓" else "✗",
                                )
                                KeyValueRow(
                                    skill.t("admin.bundles.field.created_by"),
                                    bundle.createdBy ?: "—",
                                )
                                KeyValueRow("SHA-256", bundle.manifestSha256.take(16) + "…")
                                downloadChecks[bundle.id]?.let { check ->
                                    if (check.startsWith("error:")) {
                                        AdminErrorBanner(check)
                                    } else {
                                        AdminOkBanner(
                                            skill.t("admin.bundles.download_verified") +
                                                " " + check.take(16) + "…"
                                        )
                                    }
                                }
                                Spacer(Modifier.height(6.dp))
                                OutlinedButton(onClick = {
                                    scope.launch(Dispatchers.IO) {
                                        bundleController.verifyDownload(bundle.id)
                                    }
                                }) { Text(skill.t("admin.bundles.verify_download")) }
                            }
                        }
                    }
                }
            }
        }
    }
}
