package com.giraffetechnology.qc.ui.admin

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.ui.LanguageSwitch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/** Shared header row for every Administrator screen: title, back, language. */
@Composable
fun AdminScreenHeader(
    title: String,
    languageController: LanguageController,
    backLabel: String,
    onBack: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(onClick = onBack) { Text(backLabel) }
        Spacer(Modifier.padding(horizontal = 8.dp))
        Text(title, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.weight(1f))
        LanguageSwitch(languageController)
    }
}

/** Colored status banner (matches the Operator screens' MessageBanner look). */
@Composable
fun AdminBanner(text: String, color: Color) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(color.copy(alpha = 0.12f))
            .padding(10.dp),
    ) {
        Text(text, color = color, fontSize = 13.sp)
    }
}

/** Amber "backend pending" banner — the labeled-stub presentation for WS4/5/6/7 gaps. */
@Composable
fun BackendPendingBanner(text: String) {
    AdminBanner(text, Color(0xFFB26A00))
}

@Composable
fun AdminErrorBanner(text: String) {
    AdminBanner(text, Color(0xFFB71C1C))
}

@Composable
fun AdminOkBanner(text: String) {
    AdminBanner(text, Color(0xFF2E7D32))
}

@Composable
fun KeyValueRow(key: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(
            key,
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth(0.4f),
        )
        Text(value, fontSize = 13.sp)
    }
}

/**
 * Minimal remote image loader over the factory-LAN backend (no third-party
 * image library in this app). Sends the admin session cookie so the tenant-
 * scoped photo route authorizes the request.
 */
@Composable
fun RemoteImage(
    url: String,
    cookie: String?,
    modifier: Modifier = Modifier,
    onSize: ((Int, Int) -> Unit)? = null,
) {
    var bitmap by remember(url) { mutableStateOf<ImageBitmap?>(null) }
    var failed by remember(url) { mutableStateOf(false) }

    LaunchedEffect(url) {
        val loaded = withContext(Dispatchers.IO) {
            runCatching {
                val conn = URL(url).openConnection() as HttpURLConnection
                conn.connectTimeout = 5_000
                conn.readTimeout = 15_000
                if (cookie != null) conn.setRequestProperty("Cookie", cookie)
                try {
                    if (conn.responseCode == 200) {
                        conn.inputStream.use { BitmapFactory.decodeStream(it) }
                    } else null
                } finally {
                    conn.disconnect()
                }
            }.getOrNull()
        }
        if (loaded != null) {
            onSize?.invoke(loaded.width, loaded.height)
            bitmap = loaded.asImageBitmap()
        } else {
            failed = true
        }
    }

    val bmp = bitmap
    if (bmp != null) {
        Image(bitmap = bmp, contentDescription = null, modifier = modifier)
    } else {
        Box(modifier = modifier.background(Color(0x11000000)), contentAlignment = Alignment.Center) {
            Text(if (failed) "×" else "…", fontSize = 18.sp)
        }
    }
}
