package com.giraffetechnology.qc.ui.admin

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
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminSkuController
import com.giraffetechnology.qc.admin.AdminSkuCreateState
import com.giraffetechnology.qc.admin.AdminSkuListState
import com.giraffetechnology.qc.admin.SKU_LIFECYCLE_STATES
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * SKU create / select (WS3 item 2). Landscape two-pane layout: list + PRD
 * lifecycle filter on the left, structured create form and the selected SKU
 * card on the right. Statuses come exclusively from the PRD 7-state lifecycle.
 */
@Composable
fun AdminSkuScreen(
    controller: AdminSkuController,
    languageController: LanguageController,
    onOpenStandard: (String) -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val listState by controller.listState.collectAsState()
    val createState by controller.createState.collectAsState()
    val selected by controller.selected.collectAsState()

    var query by remember { mutableStateOf("") }
    var statusFilter by remember { mutableStateOf("") }
    var filterMenuOpen by remember { mutableStateOf(false) }

    var newItemNumber by remember { mutableStateOf("") }
    var newName by remember { mutableStateOf("") }
    var newCategory by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        scope.launch(Dispatchers.IO) { controller.refresh() }
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.skus.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        Spacer(Modifier.height(12.dp))

        Row(modifier = Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            // ── Left pane: search + PRD lifecycle filter + list ──────────────
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        label = { Text(skill.t("admin.skus.search")) },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Column {
                        OutlinedButton(onClick = { filterMenuOpen = true }) {
                            Text(
                                if (statusFilter.isEmpty()) skill.t("admin.skus.status.all")
                                else skill.t("admin.skus.status.$statusFilter")
                            )
                        }
                        DropdownMenu(
                            expanded = filterMenuOpen,
                            onDismissRequest = { filterMenuOpen = false },
                        ) {
                            DropdownMenuItem(
                                text = { Text(skill.t("admin.skus.status.all")) },
                                onClick = {
                                    statusFilter = ""; filterMenuOpen = false
                                    scope.launch(Dispatchers.IO) { controller.refresh(query, "") }
                                },
                            )
                            SKU_LIFECYCLE_STATES.forEach { state ->
                                DropdownMenuItem(
                                    text = { Text(skill.t("admin.skus.status.$state")) },
                                    onClick = {
                                        statusFilter = state; filterMenuOpen = false
                                        scope.launch(Dispatchers.IO) { controller.refresh(query, state) }
                                    },
                                )
                            }
                        }
                    }
                    Button(onClick = {
                        scope.launch(Dispatchers.IO) { controller.refresh(query, statusFilter) }
                    }) { Text(skill.t("common.search")) }
                }
                Spacer(Modifier.height(8.dp))

                when (val s = listState) {
                    is AdminSkuListState.Loading -> Text(skill.t("common.loading"), fontSize = 13.sp)
                    is AdminSkuListState.Error -> AdminErrorBanner(s.message)
                    is AdminSkuListState.Loaded -> {
                        if (s.skus.isEmpty()) {
                            Text(skill.t("admin.skus.empty"), fontSize = 13.sp)
                        }
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            items(s.skus) { sku ->
                                val isSelected = selected?.id == sku.id
                                Surface(
                                    tonalElevation = 1.dp,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            scope.launch(Dispatchers.IO) { controller.select(sku.id) }
                                        }
                                        .border(
                                            width = if (isSelected) 2.dp else 0.dp,
                                            color = if (isSelected) MaterialTheme.colorScheme.primary
                                            else Color.Transparent,
                                        ),
                                ) {
                                    Column(modifier = Modifier.padding(10.dp)) {
                                        Text(sku.itemNumber, fontWeight = FontWeight.SemiBold)
                                        Text(sku.name, fontSize = 13.sp)
                                        Text(
                                            skill.t("admin.skus.status.${sku.status}")
                                                .takeIf { it != "admin.skus.status.${sku.status}" }
                                                ?: sku.status,
                                            fontSize = 11.sp,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ── Right pane: create form + selected SKU card ──────────────────
            Column(modifier = Modifier.weight(1f)) {
                Text(skill.t("admin.skus.create.title"), fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                OutlinedTextField(
                    value = newItemNumber,
                    onValueChange = { newItemNumber = it },
                    label = { Text(skill.t("admin.skus.create.item_number")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = newName,
                    onValueChange = { newName = it },
                    label = { Text(skill.t("admin.skus.create.name")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = newCategory,
                    onValueChange = { newCategory = it },
                    label = { Text(skill.t("admin.skus.create.category")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                when (val c = createState) {
                    is AdminSkuCreateState.Error -> AdminErrorBanner(c.message)
                    is AdminSkuCreateState.Created -> AdminOkBanner(skill.t("admin.skus.create.done"))
                    is AdminSkuCreateState.Creating -> Text(skill.t("common.loading"), fontSize = 13.sp)
                    else -> {}
                }
                Spacer(Modifier.height(6.dp))
                Button(onClick = {
                    scope.launch(Dispatchers.IO) {
                        controller.create(
                            newItemNumber, newName,
                            newCategory.takeIf { it.isNotBlank() }, null,
                        )
                    }
                }) { Text(skill.t("admin.skus.create.submit")) }

                Spacer(Modifier.height(16.dp))

                selected?.let { sku ->
                    Surface(tonalElevation = 2.dp, modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text("${sku.itemNumber} — ${sku.name}", fontWeight = FontWeight.SemiBold)
                            KeyValueRow(skill.t("admin.skus.field.status"), sku.status)
                            KeyValueRow(skill.t("admin.skus.field.standard"), sku.standardStatus)
                            KeyValueRow(
                                skill.t("admin.skus.field.points"),
                                sku.detectionPointCount.toString(),
                            )
                            Spacer(Modifier.height(8.dp))
                            Button(onClick = { onOpenStandard(sku.id) }) {
                                Text(skill.t("admin.skus.open_standard"))
                            }
                        }
                    }
                }
            }
        }
    }
}
