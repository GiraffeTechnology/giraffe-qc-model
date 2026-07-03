package com.giraffetechnology.qc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.i18n.LanguageController

/**
 * Administrator branch on the Pad. Standard authoring, bundles, and workstations
 * are managed on the Web admin console (see docs/ANDROID_QC_APP.md — the admin
 * page is Web-only, shared by both editions), so this screen states that plainly
 * and offers a way back. It exists so the Welcome Administrator branch is never a
 * dead end.
 */
@Composable
fun AdministratorInfoScreen(
    languageController: LanguageController,
    onBack: () -> Unit,
) {
    val skill by languageController.skill.collectAsState()

    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skill.t("welcome.administrator"), fontSize = 24.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.width(16.dp))
            LanguageSwitch(languageController)
        }
        Spacer(Modifier.width(8.dp))
        Text(
            "Standard authoring, bundle export, and workstation management run on " +
                "the Web admin console. This Pad runs the Operator inspection flow.",
            fontSize = 14.sp,
        )
        Spacer(Modifier.width(24.dp))
        OutlinedButton(onClick = onBack) { Text(skill.t("common.cancel")) }
    }
}
