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
import com.giraffetechnology.qc.sku.*
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

@Composable
fun TaskSelectionScreen(
    taskSelectionController: TaskSelectionController,
    runtimeLoader: MnnRuntimeLoader,
    skuRepository: ApiSkuRepository?,
    onTaskConfirmed: (QcTask) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val selectionState by taskSelectionController.state.collectAsState()
    val runtimeState by runtimeLoader.runtimeState.collectAsState()

    // Unconditional remember — avoids conditional composable call violation.
    val fallbackConnectionFlow = remember {
        MutableStateFlow<BackendConnectionState>(BackendConnectionState.Unknown)
    }
    val backendStateFlow = skuRepository?.connectionState ?: fallbackConnectionFlow
    val backendState by backendStateFlow.collectAsState()

    var query by remember { mutableStateOf("") }
    var selectedSku by remember { mutableStateOf<Sku?>(null) }

    // Navigate when task is confirmed.
    LaunchedEffect(selectionState) {
        if (selectionState is TaskSelectionState.TaskConfirmed) {
            onTaskConfirmed((selectionState as TaskSelectionState.TaskConfirmed).task)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Text("Select QC Task", fontSize = 24.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))

        // Status chips row
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            RuntimeStatusChip(runtimeState)
            BackendStatusChip(backendState)
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
                label         = { Text("Item number") },
                singleLine    = true,
                modifier      = Modifier.weight(1f),
            )
            Button(
                onClick  = { scope.launch { taskSelectionController.searchByItemNumber(query) } },
                enabled  = query.isNotBlank()
                    && selectionState !is TaskSelectionState.SearchingBackend,
            ) { Text("Search") }
        }
        Spacer(Modifier.height(8.dp))

        // State feedback
        when (val st = selectionState) {
            is TaskSelectionState.SearchingBackend ->
                Text("Searching backend…", color = MaterialTheme.colorScheme.primary)

            is TaskSelectionState.BackendError ->
                Text("Backend error: ${st.message}", color = MaterialTheme.colorScheme.error)

            is TaskSelectionState.MnnPending ->
                StatusBanner("MNN pending — please select SKU manually", Color(0xFFFFA000))

            is TaskSelectionState.ReviewRequired ->
                StatusBanner("review_required — please select SKU manually", Color(0xFFFFA000))

            is TaskSelectionState.NoMatch ->
                StatusBanner("No SKU match found", Color(0xFFB71C1C))

            is TaskSelectionState.ManualResults -> {
                if (st.results.isEmpty()) {
                    Text("No results for \"$query\"")
                } else {
                    Text("${st.results.size} result(s) — tap a SKU to select it")
                }
            }

            is TaskSelectionState.MatchCandidates ->
                Text("${st.result.candidates.size} photo-match candidate(s) — confirm below")

            else -> Unit
        }
        Spacer(Modifier.height(8.dp))

        // SKU result list
        val skuList: List<Sku> = when (val st = selectionState) {
            is TaskSelectionState.ManualResults   -> st.results
            is TaskSelectionState.MatchCandidates -> st.result.candidates.map { it.sku }
            else -> emptyList()
        }
        LazyColumn(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            items(skuList) { sku ->
                val isSelected = selectedSku?.id == sku.id
                Surface(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { selectedSku = sku }
                        .border(
                            width = if (isSelected) 2.dp else 0.dp,
                            color = if (isSelected)
                                MaterialTheme.colorScheme.primary
                            else Color.Transparent,
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
        Spacer(Modifier.height(8.dp))

        // Action buttons
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { scope.launch { taskSelectionController.runMatch("") } },
            ) { Text("Photo Match") }

            Spacer(Modifier.weight(1f))

            Button(
                onClick = {
                    selectedSku?.let { sku ->
                        taskSelectionController.confirmManual(
                            sku,
                            SkuResolutionMethod.MANUAL_ITEM_NUMBER,
                        )
                    }
                },
                enabled = selectedSku != null,
            ) { Text("Confirm SKU") }
        }
    }
}

@Composable
private fun RuntimeStatusChip(state: MnnRuntimeState) {
    val (label, color) = when (state) {
        is MnnRuntimeState.Ready    -> "Ready" to Color(0xFF2E7D32)
        is MnnRuntimeState.Loading  -> "MNN loading" to Color(0xFFF57F17)
        is MnnRuntimeState.NotReady -> "Local runtime not ready" to Color(0xFFB71C1C)
    }
    StatusChip(label = label, color = color)
}

@Composable
private fun BackendStatusChip(state: BackendConnectionState) {
    val (label, color) = when (state) {
        is BackendConnectionState.Unknown   -> "Backend unknown" to Color(0xFF757575)
        is BackendConnectionState.Connected -> "Connected" to Color(0xFF2E7D32)
        is BackendConnectionState.Offline   -> "Offline" to Color(0xFFB71C1C)
        is BackendConnectionState.Error     -> "Error" to Color(0xFFB71C1C)
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
