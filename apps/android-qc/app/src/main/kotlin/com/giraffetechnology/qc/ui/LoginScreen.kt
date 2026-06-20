package com.giraffetechnology.qc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun LoginScreen(onLoginSuccess: (operatorId: String) -> Unit) {
    var operatorId by remember { mutableStateOf("") }
    var password   by remember { mutableStateOf("") }
    var error      by remember { mutableStateOf<String?>(null) }

    Row(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF1A1A2E)),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.width(360.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                "GiraffeQC — Pad Login",
                color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = operatorId,
                onValueChange = { operatorId = it; error = null },
                label = { Text("操作员 ID", color = Color(0xFFAAAAAA)) },
                singleLine = true,
                colors = outlinedTextFieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = password,
                onValueChange = { password = it; error = null },
                label = { Text("密码", color = Color(0xFFAAAAAA)) },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                colors = outlinedTextFieldColors(),
                modifier = Modifier.fillMaxWidth(),
            )
            error?.let {
                Text(it, color = Color(0xFFFF6B6B), fontSize = 13.sp)
            }
            Button(
                onClick = {
                    when {
                        operatorId.isBlank() -> error = "操作员 ID 不能为空"
                        password.isBlank()   -> error = "密码不能为空"
                        else                 -> onLoginSuccess(operatorId.trim())
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF4ECDC4)),
            ) {
                Text("登录", color = Color.White, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun outlinedTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor   = Color.White,
    unfocusedTextColor = Color.White,
    focusedBorderColor = Color(0xFF4ECDC4),
    unfocusedBorderColor = Color(0xFF555577),
)
