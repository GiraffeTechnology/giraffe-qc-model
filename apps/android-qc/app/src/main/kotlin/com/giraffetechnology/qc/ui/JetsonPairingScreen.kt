package com.giraffetechnology.qc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.jetson.JetsonLanClient
import com.giraffetechnology.qc.jetson.JetsonPairingRepository
import com.giraffetechnology.qc.jetson.JetsonPairingStore
import kotlinx.coroutines.launch

/**
 * Jetson pairing screen (WS4). Two paths mirroring
 * `docs/jetson-headless-pairing.md` / `PairingAgent`: USB (physical
 * connection is the proof of presence -- just needs the Jetson's LAN IP, or
 * a fixed USB-gadget IP if that's how the device is wired) and Wi-Fi
 * (pairing window + chassis fingerprint, entered by the operator reading the
 * Jetson's physical sticker). Pairing never requires the Server to be
 * reachable (floor first, sync later) -- this screen only ever talks to the
 * Jetson directly over LAN.
 */
@Composable
fun JetsonPairingScreen(
    languageController: LanguageController,
    pairingStore: JetsonPairingRepository,
    client: JetsonLanClient,
    onPaired: () -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()

    var host by remember { mutableStateOf(pairingStore.jetsonHost ?: "") }
    var fingerprint by remember { mutableStateOf("") }
    var pairing by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    fun currentBaseUrl() = "http://${host.trim()}:${JetsonPairingStore.DEFAULT_PORT}"

    fun handleOutcome(outcome: JetsonLanClient.PairingOutcome) {
        pairing = false
        when (outcome) {
            is JetsonLanClient.PairingOutcome.Success -> {
                pairingStore.savePairing(
                    host = host.trim(),
                    port = JetsonPairingStore.DEFAULT_PORT,
                    jetsonDeviceId = outcome.handshake.jetsonDeviceId,
                    pairKey = outcome.handshake.pairKey,
                    pairingPath = outcome.handshake.pairingPath,
                )
                errorMessage = null
                onPaired()
            }
            is JetsonLanClient.PairingOutcome.Rejected -> {
                errorMessage = skill.t("pad.jetson.pairing.failed", mapOf("reason" to outcome.reason))
            }
            is JetsonLanClient.PairingOutcome.Unreachable -> {
                errorMessage = skill.t("pad.jetson.pairing.failed", mapOf("reason" to "unreachable"))
            }
        }
    }

    fun pairUsb() {
        if (host.isBlank()) {
            errorMessage = skill.t("pad.jetson.pairing.failed", mapOf("reason" to "host_required"))
            return
        }
        pairing = true
        errorMessage = null
        scope.launch {
            val outcome = client.pairUsb(currentBaseUrl(), pairingStore.padDeviceId, pairingStore.padPubkey)
            handleOutcome(outcome)
        }
    }

    fun pairWifi() {
        if (host.isBlank() || fingerprint.isBlank()) {
            errorMessage = skill.t("pad.jetson.pairing.failed", mapOf("reason" to "host_and_fingerprint_required"))
            return
        }
        pairing = true
        errorMessage = null
        scope.launch {
            val outcome = client.pairWifi(currentBaseUrl(), pairingStore.padDeviceId, pairingStore.padPubkey, fingerprint.trim())
            handleOutcome(outcome)
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(skill.t("pad.jetson.pairing.title"), fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            LanguageSwitch(languageController)
        }

        if (pairingStore.isPaired) {
            Surface(color = Color(0xFF1B5E20).copy(alpha = 0.15f), modifier = Modifier.fillMaxWidth()) {
                Text(
                    skill.t("pad.jetson.pairing.success", mapOf("device" to (pairingStore.jetsonDeviceId ?: ""))),
                    modifier = Modifier.padding(12.dp),
                    color = Color(0xFF1B5E20),
                    fontWeight = FontWeight.Bold,
                )
            }
            OutlinedButton(onClick = {
                pairingStore.clearPairing()
                host = ""
            }) { Text(skill.t("pad.jetson.pairing.unpair")) }
            Divider()
        }

        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text(skill.t("pad.jetson.pairing.host_hint")) },
            singleLine = true,
            enabled = !pairing,
            modifier = Modifier.fillMaxWidth(),
        )

        Text(skill.t("pad.jetson.pairing.usb_instruction"), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Button(onClick = { pairUsb() }, enabled = !pairing) { Text(skill.t("pad.jetson.pairing.usb_button")) }

        Divider()

        Text(skill.t("pad.jetson.pairing.wifi_instruction"), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(
            value = fingerprint,
            onValueChange = { fingerprint = it },
            label = { Text(skill.t("pad.jetson.pairing.fingerprint_hint")) },
            singleLine = true,
            enabled = !pairing,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(onClick = { pairWifi() }, enabled = !pairing) { Text(skill.t("pad.jetson.pairing.wifi_button")) }

        errorMessage?.let {
            Text(it, color = Color(0xFFB71C1C), fontSize = 13.sp)
        }

        Spacer(Modifier.weight(1f))
        Row {
            Spacer(Modifier.width(1.dp))
            OutlinedButton(onClick = onBack, enabled = !pairing) { Text(skill.t("common.cancel")) }
        }
    }
}
