package com.giraffetechnology.qc.ui

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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.submit.OutboxEntry
import com.giraffetechnology.qc.submit.OutboxUploader
import com.giraffetechnology.qc.submit.PadOutbox
import kotlinx.coroutines.launch

/**
 * Sync status (S6) — shows the result outbox and drains it to the Server on
 * demand. Inspection is offline, so results accumulate here and upload when a
 * connection is available; the uploader is idempotent (Server dedupes on
 * client_job_id), so "Upload Now" is always safe to retry.
 */
@Composable
fun OperatorSyncStatusScreen(
    languageController: LanguageController,
    outbox: PadOutbox,
    uploader: OutboxUploader,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()

    var entries by remember { mutableStateOf<List<OutboxEntry>>(emptyList()) }
    var pendingCount by remember { mutableStateOf(0) }
    var uploading by remember { mutableStateOf(false) }
    var lastMessage by remember { mutableStateOf<String?>(null) }

    suspend fun refresh() {
        entries = outbox.all()
        pendingCount = outbox.pendingCount()
    }

    LaunchedEffect(Unit) { refresh() }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row {
            Text(skill.t("pad.sync.title"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            LanguageSwitch(languageController)
        }

        Text(
            if (pendingCount == 0) skill.t("pad.sync.none_pending")
            else skill.t("pad.sync.pending", mapOf("count" to pendingCount.toString())),
            fontWeight = FontWeight.SemiBold,
        )
        lastMessage?.let { Text(it, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant) }

        Divider()
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            items(entries) { entry ->
                val s = entry.submission
                Surface(
                    color = if (entry.uploaded) Color(0xFFE8F5E9) else Color(0xFFFFF8E1),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(Modifier.padding(10.dp)) {
                        Text("${s.itemNumber} — ${s.humanDecision.wire}", fontWeight = FontWeight.SemiBold, fontSize = 13.sp)
                        Text(
                            "rev=${s.standardRevisionId ?: "—"} · bundle=${s.bundleVersion ?: "—"}",
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(
                            if (entry.uploaded) skill.t("pad.sync.none_pending") else skill.t("pad.sync.title"),
                            fontSize = 10.sp,
                            color = if (entry.uploaded) Color(0xFF1B5E20) else Color(0xFF8D5A00),
                        )
                    }
                }
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            OutlinedButton(onClick = onBack) { Text(skill.t("common.cancel")) }
            Spacer(Modifier.weight(1f))
            Button(
                onClick = {
                    uploading = true
                    scope.launch {
                        val outcome = uploader.uploadPending()
                        lastMessage = outcome.error ?: skill.t("pad.sync.none_pending")
                        refresh()
                        uploading = false
                    }
                },
                enabled = !uploading && pendingCount > 0,
            ) { Text(skill.t("pad.sync.upload_now")) }
        }
    }
}
