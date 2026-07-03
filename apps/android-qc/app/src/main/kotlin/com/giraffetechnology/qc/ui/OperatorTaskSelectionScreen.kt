package com.giraffetechnology.qc.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.operator.OperatorTaskSelectionController
import com.giraffetechnology.qc.operator.OperatorTaskState
import com.giraffetechnology.qc.sku.QcTask
import kotlinx.coroutines.launch

/**
 * Operator Task Selection (S5 §8.1) — offline search of installed standards.
 *
 * Every result comes from the local [OperatorTaskSelectionController] over the
 * on-device store; there is no LAN backend call on this screen. The two spec
 * messages (no standards installed / SKU not found) are resolved through the
 * language skill from the controller's message keys.
 */
@Composable
fun OperatorTaskSelectionScreen(
    controller: OperatorTaskSelectionController,
    languageController: LanguageController,
    onTaskConfirmed: (QcTask) -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val state by controller.state.collectAsState()

    var query by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf<InstalledSku?>(null) }

    // Navigate away on confirmation; clear stale selection on any list refresh.
    androidx.compose.runtime.LaunchedEffect(state) {
        when (val s = state) {
            is OperatorTaskState.Confirmed -> onTaskConfirmed(s.task)
            else -> selected = null
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skill.t("pad.task.title"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            LanguageSwitch(languageController)
        }
        Text(
            skill.t("pad.task.offline_note"),
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text(skill.t("pad.task.search_placeholder")) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Button(onClick = { scope.launch { controller.search(query) } }) {
                Text(skill.t("common.search"))
            }
        }
        Spacer(Modifier.height(12.dp))

        when (val s = state) {
            is OperatorTaskState.NoStandardsInstalled ->
                MessageBanner(skill.t(OperatorTaskSelectionController.KEY_NO_STANDARDS), Color(0xFFB71C1C))

            is OperatorTaskState.SkuNotFound ->
                MessageBanner(skill.t(OperatorTaskSelectionController.KEY_SKU_NOT_FOUND), Color(0xFFF57F17))

            is OperatorTaskState.Results -> {
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(s.skus) { sku ->
                        val isSelected = selected?.skuId == sku.skuId
                        Surface(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { selected = sku }
                                .border(
                                    width = if (isSelected) 2.dp else 0.dp,
                                    color = if (isSelected) MaterialTheme.colorScheme.primary else Color.Transparent,
                                ),
                            tonalElevation = if (isSelected) 4.dp else 1.dp,
                        ) {
                            Column(Modifier.padding(12.dp)) {
                                Text(sku.itemNumber, fontWeight = FontWeight.Bold)
                                Text(sku.name, fontSize = 13.sp)
                            }
                        }
                    }
                }
            }

            else -> Spacer(Modifier.weight(1f))
        }

        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            androidx.compose.material3.OutlinedButton(onClick = onBack) {
                Text(skill.t("common.cancel"))
            }
            Spacer(Modifier.weight(1f))
            Button(
                onClick = { selected?.let { s -> scope.launch { controller.confirm(s.skuId) } } },
                enabled = selected != null,
            ) { Text(skill.t("pad.task.confirm")) }
        }
    }
}

@Composable
private fun MessageBanner(message: String, color: Color) {
    Surface(color = color.copy(alpha = 0.12f), modifier = Modifier.fillMaxWidth()) {
        Text(message, modifier = Modifier.padding(12.dp), color = color, fontWeight = FontWeight.SemiBold)
    }
}
