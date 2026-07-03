package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.work.ConversationEntry
import com.giraffetechnology.qc.work.ConversationRole

/**
 * Scrollable conversation/inspection log (S6 §8.2 right-middle) with the §3.4
 * bubble style shared with Web: OPERATOR bubbles are right-aligned with the
 * primary container color; every system-side kind is left-aligned, and
 * WARNING/ERROR carry distinct emphasis colors.
 */
@Composable
fun ConversationLog(
    entries: List<ConversationEntry>,
    modifier: Modifier = Modifier,
) {
    val listState = rememberLazyListState()
    LaunchedEffect(entries.size) {
        if (entries.isNotEmpty()) listState.animateScrollToItem(entries.size - 1)
    }

    LazyColumn(
        state = listState,
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        itemsIndexed(entries) { _, entry -> ConversationBubble(entry) }
    }
}

@Composable
private fun ConversationBubble(entry: ConversationEntry) {
    val isOperator = entry.role == ConversationRole.OPERATOR
    val (bg, fg) = bubbleColors(entry.role)

    Box(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .align(if (isOperator) Alignment.CenterEnd else Alignment.CenterStart)
                .widthIn(max = 320.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(bg)
                .padding(horizontal = 10.dp, vertical = 6.dp),
        ) {
            Text(entry.text, color = fg, fontSize = 12.sp)
        }
    }
}

@Composable
private fun bubbleColors(role: ConversationRole): Pair<Color, Color> = when (role) {
    ConversationRole.OPERATOR ->
        MaterialTheme.colorScheme.primaryContainer to MaterialTheme.colorScheme.onPrimaryContainer
    ConversationRole.WARNING ->
        Color(0xFFFFF3E0) to Color(0xFF8D5A00)
    ConversationRole.ERROR ->
        Color(0xFFFFEBEE) to Color(0xFFB71C1C)
    ConversationRole.DETECTION_RESULT ->
        MaterialTheme.colorScheme.secondaryContainer to MaterialTheme.colorScheme.onSecondaryContainer
    else ->
        MaterialTheme.colorScheme.surfaceVariant to MaterialTheme.colorScheme.onSurfaceVariant
}
