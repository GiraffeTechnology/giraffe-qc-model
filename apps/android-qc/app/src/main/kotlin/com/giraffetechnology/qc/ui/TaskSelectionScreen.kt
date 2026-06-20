package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.sku.*

@Composable
fun TaskSelectionScreen(
    state: TaskSelectionState,
    runtimeState: MnnRuntimeState,
    onManualSearch: (String) -> Unit,
    onManualConfirm: (Sku) -> Unit,
    onStartPhotoMatch: () -> Unit,
    onConfirmCandidate: (SkuCandidate) -> Unit,
    onSwitchToManual: () -> Unit,
) {
    var mode by remember { mutableStateOf(Mode.MANUAL) }
    var searchQuery by remember { mutableStateOf("") }

    Row(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF1A1A2E)),
    ) {
        // ── Left: content area (weight=3) ──
        Column(
            modifier = Modifier
                .weight(3f)
                .fillMaxHeight()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "任务选择 — Task Selection",
                color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold,
            )

            // Mode toggle
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ModeTab("手动选择", mode == Mode.MANUAL) { mode = Mode.MANUAL }
                ModeTab("拍照匹配", mode == Mode.PHOTO_MATCH) { mode = Mode.PHOTO_MATCH }
            }

            Divider(color = Color(0xFF444466))

            when (mode) {
                Mode.MANUAL -> ManualModeContent(
                    state        = state,
                    searchQuery  = searchQuery,
                    onQueryChange = { searchQuery = it },
                    onSearch     = { onManualSearch(searchQuery) },
                    onConfirm    = onManualConfirm,
                )
                Mode.PHOTO_MATCH -> PhotoMatchContent(
                    state              = state,
                    runtimeState       = runtimeState,
                    onStartCapture     = onStartPhotoMatch,
                    onConfirmCandidate = onConfirmCandidate,
                    onSwitchToManual   = { mode = Mode.MANUAL; onSwitchToManual() },
                )
            }
        }

        // ── Right: status panel (weight=1) ──
        Column(
            modifier = Modifier
                .weight(1f)
                .fillMaxHeight()
                .background(Color(0xFF12122A))
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("状态", color = Color(0xFFAAAAAA), fontSize = 12.sp)
            Divider(color = Color(0xFF333355))
            val mnnLabel = when (runtimeState) {
                MnnRuntimeState.Ready    -> "MNN: Ready"
                MnnRuntimeState.Loading  -> "MNN: Loading…"
                MnnRuntimeState.NotReady -> "MNN: Pending"
                is MnnRuntimeState.Error -> "MNN: Error"
            }
            val mnnColor = when (runtimeState) {
                MnnRuntimeState.Ready    -> Color(0xFF6BCB77)
                MnnRuntimeState.Loading  -> Color(0xFF4ECDC4)
                MnnRuntimeState.NotReady -> Color(0xFFFFD93D)
                is MnnRuntimeState.Error -> Color(0xFFFF6B6B)
            }
            StatusChip(mnnLabel, mnnColor)

            val stateLabel = when (state) {
                TaskSelectionState.Idle            -> "Idle"
                TaskSelectionState.ManualSearching -> "Searching…"
                is TaskSelectionState.ManualResults-> "${(state as TaskSelectionState.ManualResults).results.size} results"
                TaskSelectionState.CapturingForMatch -> "Capturing…"
                TaskSelectionState.Matching        -> "Matching…"
                is TaskSelectionState.MatchCandidates -> "Candidates ready"
                TaskSelectionState.MnnPending      -> "MNN pending"
                is TaskSelectionState.TaskConfirmed-> "Task confirmed"
                is TaskSelectionState.Error        -> "Error"
            }
            StatusChip(stateLabel, Color(0xFFCCCCCC))
        }
    }
}

@Composable
private fun ManualModeContent(
    state: TaskSelectionState,
    searchQuery: String,
    onQueryChange: (String) -> Unit,
    onSearch: () -> Unit,
    onConfirm: (Sku) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = searchQuery,
            onValueChange = onQueryChange,
            label = { Text("货号 Item Number", color = Color(0xFFAAAAAA)) },
            singleLine = true,
            modifier = Modifier.weight(1f),
            colors = outlinedTextFieldColors(),
        )
        Button(onClick = onSearch) { Text("搜索") }
    }

    when (state) {
        TaskSelectionState.ManualSearching -> CircularProgressIndicator(color = Color(0xFF4ECDC4))
        is TaskSelectionState.ManualResults -> {
            if (state.results.isEmpty()) {
                Text("未找到匹配商品", color = Color(0xFFAAAAAA))
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(state.results) { sku ->
                        SkuRow(sku = sku, onConfirm = { onConfirm(sku) })
                    }
                }
            }
        }
        else -> Unit
    }
}

@Composable
private fun PhotoMatchContent(
    state: TaskSelectionState,
    runtimeState: MnnRuntimeState,
    onStartCapture: () -> Unit,
    onConfirmCandidate: (SkuCandidate) -> Unit,
    onSwitchToManual: () -> Unit,
) {
    when {
        runtimeState == MnnRuntimeState.NotReady || runtimeState is MnnRuntimeState.Error -> {
            Text(
                "MNN pending — Local runtime not ready.\n请使用手动选择模式。",
                color = Color(0xFFFFD93D), fontSize = 14.sp,
            )
            Spacer(Modifier.height(8.dp))
            OutlinedButton(onClick = onSwitchToManual) { Text("切换到手动选择") }
        }
        state == TaskSelectionState.CapturingForMatch -> {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("请对准单元拍照…", color = Color.White)
                Text("(相机预览在这里展示)", color = Color(0xFFAAAAAA), fontSize = 12.sp)
            }
        }
        state == TaskSelectionState.Matching -> {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(Modifier.size(20.dp), color = Color(0xFF4ECDC4))
                Text("MNN 匹配中…", color = Color.White)
            }
        }
        state is TaskSelectionState.MatchCandidates -> {
            val result = state.result
            Text("匹配候选 — 请操作员确认", color = Color.White, fontWeight = FontWeight.Bold)
            if (result.status == MatchStatus.REVIEW_REQUIRED) {
                Text("✕ 似然度较低或候选相近，请仔细检查", color = Color(0xFFFFD93D), fontSize = 13.sp)
            }
            if (result.candidates.isEmpty()) {
                Text("未找到匹配的商品", color = Color(0xFFAAAAAA))
            } else {
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(result.candidates) { candidate ->
                        CandidateRow(candidate, onConfirm = { onConfirmCandidate(candidate) })
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onSwitchToManual,
                modifier = Modifier.fillMaxWidth(),
                border = ButtonDefaults.outlinedButtonBorder.copy(),
            ) {
                Text("以上均不匹配 — 切换到手动选择")
            }
        }
        state == TaskSelectionState.MnnPending -> {
            Text(
                "MNN pending — Local runtime not ready.\n匹配无法执行，请使用手动选择。",
                color = Color(0xFFFFD93D),
            )
            OutlinedButton(onClick = onSwitchToManual) { Text("切换到手动选择") }
        }
        else -> {
            Text("请对准单元并拍照，进行 MNN 匹配。", color = Color(0xFFAAAAAA))
            Spacer(Modifier.height(8.dp))
            Button(onClick = onStartCapture) { Text("拍照匹配") }
        }
    }
}

@Composable
private fun SkuRow(sku: Sku, onConfirm: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF252540), RoundedCornerShape(6.dp))
            .padding(10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(sku.itemNumber, color = Color.White, fontWeight = FontWeight.Medium)
            Text(sku.name, color = Color(0xFFAAAAAA), fontSize = 12.sp)
        }
        Button(
            onClick = onConfirm,
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4ECDC4)),
        ) { Text("确认", fontSize = 12.sp) }
    }
}

@Composable
private fun CandidateRow(candidate: SkuCandidate, onConfirm: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFF252540), RoundedCornerShape(6.dp))
            .padding(10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(candidate.sku.name, color = Color.White, fontWeight = FontWeight.Medium)
            Text(candidate.sku.itemNumber, color = Color(0xFFAAAAAA), fontSize = 12.sp)
            Text(
                "相似度: ${"%d".format((candidate.similarity * 100).toInt())}%",
                color = Color(0xFF6BCB77), fontSize = 12.sp,
            )
        }
        Button(
            onClick = onConfirm,
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6BCB77)),
        ) { Text("确认此 SKU", fontSize = 11.sp) }
    }
}

@Composable
private fun ModeTab(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        modifier = Modifier.clickable(onClick = onClick),
        color = if (selected) Color(0xFF4ECDC4) else Color(0xFF2A2A4A),
        shape = RoundedCornerShape(6.dp),
    ) {
        Text(
            label, color = Color.White, fontSize = 13.sp,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
        )
    }
}

@Composable
private fun StatusChip(label: String, color: Color) {
    Surface(
        color = color.copy(alpha = 0.15f),
        shape = RoundedCornerShape(4.dp),
    ) {
        Text(
            label, color = color, fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun outlinedTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor   = Color.White,
    unfocusedTextColor = Color.White,
    focusedBorderColor = Color(0xFF4ECDC4),
    unfocusedBorderColor = Color(0xFF555577),
)

private enum class Mode { MANUAL, PHOTO_MATCH }
