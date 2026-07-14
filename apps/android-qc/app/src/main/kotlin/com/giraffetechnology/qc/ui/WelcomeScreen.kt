package com.giraffetechnology.qc.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.i18n.LanguageController

/**
 * Welcome screen (S5 §3.1) — shared visual spec with Web.
 *
 * Giraffe icon, Administrator / Operator branches, and the global language
 * switch. Landscape-first: both branches are visible without scrolling. All
 * labels come through the language skill; nothing is hard-coded.
 */
@Composable
fun WelcomeScreen(
    languageController: LanguageController,
    onAdministrator: () -> Unit,
    onOperator: () -> Unit,
) {
    val skill by languageController.skill.collectAsState()
    val context = LocalContext.current
    val brandIcon = remember(context) {
        requireNotNull(
            context.assets.open("giraffe-qc-model-icon.png").use(BitmapFactory::decodeStream)
        ).asImageBitmap()
    }

    Box(modifier = Modifier.fillMaxSize()) {
        LanguageSwitch(
            languageController = languageController,
            modifier = Modifier.align(Alignment.TopEnd).padding(12.dp),
        )

        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Image(
                bitmap = brandIcon,
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier.width(96.dp).height(96.dp),
            )
            Spacer(Modifier.height(8.dp))
            Text(skill.t("welcome.title"), fontSize = 30.sp, fontWeight = FontWeight.Bold)
            Text(
                skill.t("welcome.subtitle"),
                fontSize = 14.sp,
                fontWeight = FontWeight.Normal,
            )
            Spacer(Modifier.height(32.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                OutlinedButton(onClick = onAdministrator) {
                    Text(skill.t("welcome.administrator"))
                }
                Button(onClick = onOperator) {
                    Text(skill.t("welcome.operator"))
                }
            }
        }
    }
}
