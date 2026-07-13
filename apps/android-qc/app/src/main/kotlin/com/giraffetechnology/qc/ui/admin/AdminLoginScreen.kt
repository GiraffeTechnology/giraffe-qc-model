package com.giraffetechnology.qc.ui.admin

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
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.admin.AdminLoginController
import com.giraffetechnology.qc.admin.AdminLoginState
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.ui.LanguageSwitch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Administrator login (WS3 item 1). Authenticates against the server's admin
 * session endpoint; the resulting identity is bound to every admin action for
 * audit purposes. Real network call — no local bypass.
 */
@Composable
fun AdminLoginScreen(
    controller: AdminLoginController,
    languageController: LanguageController,
    onLoggedIn: () -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val state by controller.state.collectAsState()

    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var tenant by remember { mutableStateOf("demo") }

    LaunchedEffect(state) {
        if (state is AdminLoginState.LoggedIn) onLoggedIn()
    }

    Box(modifier = Modifier.fillMaxSize()) {
        LanguageSwitch(
            languageController,
            modifier = Modifier.align(Alignment.TopEnd).padding(12.dp),
        )
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Text(skill.t("admin.login.title"), fontSize = 26.sp, fontWeight = FontWeight.Bold)
            Text(skill.t("admin.login.subtitle"), fontSize = 13.sp)
            Spacer(Modifier.height(20.dp))

            OutlinedTextField(
                value = username,
                onValueChange = { username = it },
                label = { Text(skill.t("admin.login.username")) },
                singleLine = true,
                modifier = Modifier.width(360.dp),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = password,
                onValueChange = { password = it },
                label = { Text(skill.t("admin.login.password")) },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.width(360.dp),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = tenant,
                onValueChange = { tenant = it },
                label = { Text(skill.t("admin.login.tenant")) },
                singleLine = true,
                modifier = Modifier.width(360.dp),
            )
            Spacer(Modifier.height(16.dp))

            when (val s = state) {
                is AdminLoginState.Error -> {
                    AdminErrorBanner(
                        skill.t(s.messageKey) + (s.detail?.let { " ($it)" } ?: "")
                    )
                    Spacer(Modifier.height(8.dp))
                }
                is AdminLoginState.Loading -> {
                    Text(skill.t("common.loading"), fontSize = 13.sp)
                    Spacer(Modifier.height(8.dp))
                }
                else -> {}
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = onBack) { Text(skill.t("common.cancel")) }
                Button(
                    onClick = {
                        scope.launch(Dispatchers.IO) {
                            controller.login(username, password, tenant)
                        }
                    },
                    enabled = state !is AdminLoginState.Loading,
                ) {
                    Text(skill.t("admin.login.submit"))
                }
            }
        }
    }
}
