package com.giraffetechnology.qc.ui

import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.contracts.GiraffeLanguageSkill
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.sku.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

/** Tracks which list entry is selected, preserving the full source for correct confirmation. */
private sealed class SelectedSkuSource {
    abstract val sku: Sku
    data class Manual(override val sku: Sku) : SelectedSkuSource()
    data class MnnCandidate(val candidate: SkuCandidate) : SelectedSkuSource() {
        override val sku: Sku get() = candidate.sku
    }
}

/**
 * Returns true when a TaskSelectionState transition should clear the current selection.
 * TaskConfirmed is excluded — navigation fires before the selection could be misused.
 */
internal fun shouldClearSelection(state: TaskSelectionState): Boolean = when (state) {
    is TaskSelectionState.SearchingBackend,
    is TaskSelectionState.ManualResults,
    is TaskSelectionState.MatchCandidates,
    is TaskSelectionState.BackendError,
    is TaskSelectionState.NoMatch,
    is TaskSelectionState.ReviewRequired,
    is TaskSelectionState.MnnPending -> true
    else -> false
}

@Composable
fun TaskSelectionScreen(
    taskSelectionController: TaskSelectionController,
    runtimeLoader: MnnRuntime,
    skuRepository: ApiSkuRepository?,
    languageController: LanguageController,
    onTaskConfirmed: (QcTask) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val selectionState by taskSelectionController.state.collectAsState()
    val runtimeState by runtimeLoader.runtimeState.collectAsState()
    val skill by languageController.skill.collectAsState()

    // Unconditional remember — avoids conditional composable call violation.
    val fallbackConnectionFlow = remember {
        MutableStateFlow<BackendConnectionState>(BackendConnectionState.Unknown)
    }
    val backendStateFlow = skuRepository?.connectionState ?: fallbackConnectionFlow
    val backendState by backendStateFlow.collectAsState()

    var query by remember { mutableStateOf("") }
    var selectedSource by remember { mutableStateOf<SelectedSkuSource?>(null) }

    // Navigate on TaskConfirmed; clear stale selection on every other result-bearing state.
    LaunchedEffect(selectionState) {
        when (val st = selectionState) {
            is TaskSelectionState.TaskConfirmed -> onTaskConfirmed(st.task)
            else -> if (shouldClearSelection(selectionState)) selectedSource = null
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skill.t("pad.task.title"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            LanguageSwitch(languageController)
        }
        Spacer(Modifier.height(8.dp))

        // Status chips row
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RuntimeStatusChip(runtimeState, skill)
            BackendStatusChip(backendState, skill)
        }
        Spacer(Modifier.height(16.dp))

        // Search row
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value         = query,
                onValueChange = { query = it },
                label         = { Text(skill.t("admin.skus.create.item_number")) },
                singleLine    = true,
                modifier      = Modifier.weight(1f),
            )
            Button(
                onClick = {
                    selectedSource = null
                    scope.launch { taskSelectionController.searchByItemNumber(query) }
                },
                enabled  = query.isNotBlank()
                    && selectionState !is TaskSelectionState.SearchingBackend,
            ) { Text(skill.t("common.search")) }
        }
        Spacer(Modifier.height(8.dp))

        // State feedback
        when (val st = selectionState) {
            is TaskSelectionState.SearchingBackend ->
                Text(skill.t("legacy.task.searching_backend"), color = MaterialTheme.colorScheme.primary)

            is TaskSelectionState.BackendError ->
                Text(
                    skill.t("legacy.task.backend_error", mapOf("message" to st.message)),
                    color = MaterialTheme.colorScheme.error,
                )

            is TaskSelectionState.MnnPending ->
                StatusBanner(skill.t("legacy.task.mnn_pending"), Color(0xFFFFA000))

            is TaskSelectionState.ReviewRequired ->
                StatusBanner(skill.t("legacy.task.review_manual"), Color(0xFFFFA000))

            is TaskSelectionState.NoMatch ->
                StatusBanner(skill.t("legacy.task.no_match"), Color(0xFFB71C1C))

            is TaskSelectionState.ManualResults -> {
                if (st.results.isEmpty()) {
                    Text(skill.t("legacy.task.no_results", mapOf("query" to query)))
                } else {
                    Text(skill.t("legacy.task.results_count", mapOf("count" to st.results.size.toString())))
                }
            }

            is TaskSelectionState.MatchCandidates ->
                Text(skill.t(
                    "legacy.task.candidates_count",
                    mapOf("count" to st.result.candidates.size.toString()),
                ))

            else -> Unit
        }
        Spacer(Modifier.height(8.dp))

        // SKU source list — preserves candidate reference for MNN confirmation.
        val sourceList: List<SelectedSkuSource> = when (val st = selectionState) {
            is TaskSelectionState.ManualResults   ->
                st.results.map { SelectedSkuSource.Manual(it) }
            is TaskSelectionState.MatchCandidates ->
                st.result.candidates.map { SelectedSkuSource.MnnCandidate(it) }
            else -> emptyList()
        }
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            items(sourceList) { source ->
                val isSelected = selectedSource == source
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { selectedSource = source }
                        .border(
                            width = if (isSelected) 2.dp else 0.dp,
                            color = if (isSelected)
                                MaterialTheme.colorScheme.primary
                            else Color.Transparent,
                        ),
                    tonalElevation = if (isSelected) 4.dp else 1.dp,
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text(source.sku.itemNumber, fontWeight = FontWeight.Bold)
                        Text(source.sku.name, fontSize = 13.sp)
                        if (source is SelectedSkuSource.MnnCandidate) {
                            Text(
                                skill.t(
                                    "legacy.task.match",
                                    mapOf("percent" to (source.candidate.similarity * 100).toInt().toString()),
                                ),
                                fontSize = 11.sp,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(8.dp))

        // Action buttons
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { scope.launch { taskSelectionController.runMatch("") } },
            ) { Text(skill.t("legacy.task.photo_match")) }

            Spacer(Modifier.weight(1f))

            Button(
                onClick = {
                    when (val src = selectedSource) {
                        is SelectedSkuSource.MnnCandidate ->
                            taskSelectionController.confirmCandidate(src.candidate)
                        is SelectedSkuSource.Manual ->
                            scope.launch {
                                taskSelectionController.confirmManual(
                                    src.sku,
                                    SkuResolutionMethod.MANUAL_ITEM_NUMBER,
                                )
                            }
                        null -> Unit
                    }
                },
                enabled = selectedSource != null,
            ) { Text(skill.t("pad.task.confirm")) }
        }
    }
}

@Composable
private fun RuntimeStatusChip(state: MnnRuntimeState, skill: GiraffeLanguageSkill) {
    val (label, color) = when (state) {
        is MnnRuntimeState.Ready    -> skill.t("readiness.model_ready") to Color(0xFF2E7D32)
        is MnnRuntimeState.Loading  -> skill.t("legacy.task.mnn_loading") to Color(0xFFF57F17)
        is MnnRuntimeState.NotReady -> skill.t("readiness.local_runtime_not_ready") to Color(0xFFB71C1C)
    }
    StatusChip(label = label, color = color)
}

@Composable
private fun BackendStatusChip(state: BackendConnectionState, skill: GiraffeLanguageSkill) {
    val (label, color) = when (state) {
        is BackendConnectionState.Unknown   -> skill.t("legacy.task.backend_unknown") to Color(0xFF757575)
        is BackendConnectionState.Connected -> skill.t("legacy.task.connected") to Color(0xFF2E7D32)
        is BackendConnectionState.Offline   -> skill.t("readiness.offline") to Color(0xFFB71C1C)
        is BackendConnectionState.Error     -> skill.t("legacy.task.error") to Color(0xFFB71C1C)
    }
    StatusChip(label = label, color = color)
}

@Composable
private fun StatusChip(label: String, color: Color) {
    Surface(
        color = color.copy(alpha = 0.15f),
        shape = MaterialTheme.shapes.small,
    ) {
        Text(
            label,
            modifier   = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            color      = color,
            fontSize   = 12.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun StatusBanner(message: String, color: Color) {
    Surface(
        color    = color.copy(alpha = 0.12f),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            message,
            modifier   = Modifier.padding(10.dp),
            color      = color,
            fontWeight = FontWeight.SemiBold,
        )
    }
}
