package com.giraffetechnology.qc.ui

import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.viewinterop.AndroidView
import com.giraffetechnology.qc.camera.CameraXCaptureController

/**
 * Embeds a CameraX PreviewView in Compose.
 *
 * AndroidView.update calls bind() after factory; the isBound guard in the controller
 * prevents repeated binds on recomposition. DisposableEffect calls unbind() on disposal.
 */
@Composable
fun CameraPreviewPane(
    controller: CameraXCaptureController,
    modifier: Modifier = Modifier,
) {
    val lifecycleOwner = LocalLifecycleOwner.current

    DisposableEffect(controller) {
        onDispose { controller.unbind() }
    }

    AndroidView(
        factory = { ctx ->
            PreviewView(ctx).apply { scaleType = PreviewView.ScaleType.FIT_CENTER }
        },
        update = { view ->
            controller.bind(lifecycleOwner, view.surfaceProvider)
        },
        modifier = modifier,
    )
}
