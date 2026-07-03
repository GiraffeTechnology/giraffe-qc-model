package com.giraffetechnology.qc.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.File

/**
 * Standard/reference image for the selected SKU (S6 §8.2 right-top, 4:3).
 *
 * Installed standard photos are local files (populated by the S5 bundle import),
 * so the pane decodes the file directly with [BitmapFactory] — no image-loading
 * library dependency. When no local file is available it shows a labeled
 * placeholder rather than a blank box.
 */
@Composable
fun ReferenceImagePane(
    localPhotoPath: String?,
    placeholderLabel: String,
    modifier: Modifier = Modifier,
) {
    val bitmap = remember(localPhotoPath) {
        localPhotoPath
            ?.takeIf { it.isNotBlank() && File(it).exists() }
            ?.let { runCatching { BitmapFactory.decodeFile(it) }.getOrNull() }
    }

    Box(
        modifier = modifier.background(Color(0xFF202020)),
        contentAlignment = Alignment.Center,
    ) {
        if (bitmap != null) {
            Image(
                bitmap = bitmap.asImageBitmap(),
                contentDescription = placeholderLabel,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Text(
                placeholderLabel,
                color = Color(0xFFBBBBBB),
                fontSize = 12.sp,
                modifier = Modifier.padding(12.dp),
            )
        }
    }
}
