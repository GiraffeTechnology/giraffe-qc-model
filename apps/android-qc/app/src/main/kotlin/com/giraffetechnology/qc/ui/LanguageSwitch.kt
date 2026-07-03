package com.giraffetechnology.qc.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.giraffetechnology.qc.i18n.LanguageController

/**
 * Global language-switch control present on every Pad screen (S5 §3.3).
 *
 * Uses the same [LanguageController] (the `giraffe-language-skill` seam) as the
 * rest of the app, so a selection here re-localizes every screen live. The globe
 * glyph is a text emoji — no drawable asset is needed.
 */
@Composable
fun LanguageSwitch(
    languageController: LanguageController,
    modifier: Modifier = Modifier,
) {
    val current by languageController.locale.collectAsState()
    var expanded by remember { mutableStateOf(false) }

    Box(modifier) {
        TextButton(onClick = { expanded = true }) {
            Text("🌐 ${localeDisplayName(current)}")
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            languageController.supportedLocales.forEach { tag ->
                DropdownMenuItem(
                    text = { Text(localeDisplayName(tag)) },
                    onClick = {
                        languageController.select(tag)
                        expanded = false
                    },
                )
            }
        }
    }
}

/** Endonym for a supported locale tag (each language shown in its own script). */
internal fun localeDisplayName(tag: String): String = when (tag) {
    "en" -> "English"
    "zh-CN" -> "简体中文"
    "ja" -> "日本語"
    else -> tag
}
