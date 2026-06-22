package com.giraffetechnology.qc.camera

import android.content.Context
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import com.giraffetechnology.qc.capture.CapturedPhoto
import com.giraffetechnology.qc.capture.NormalizedBox
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import java.io.File
import java.util.UUID
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Production CameraX controller for still-image capture.
 *
 * bind() wires Preview + ImageCapture to the given lifecycle; isBound guard prevents double-bind
 * on recomposition. captureStill() saves a JPEG to app-private filesDir/captures/ and returns
 * CapturedPhoto. unbind() is called on composable disposal.
 */
class CameraXCaptureController(private val context: Context) {

    private val _isReady = MutableStateFlow(false)
    val isReady: StateFlow<Boolean> = _isReady.asStateFlow()

    @Volatile private var imageCapture: ImageCapture? = null
    @Volatile private var cameraProvider: ProcessCameraProvider? = null
    @Volatile private var isBound = false

    fun bind(lifecycleOwner: LifecycleOwner, surfaceProvider: Preview.SurfaceProvider) {
        if (isBound) return
        isBound = true
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener(
            {
                val provider = runCatching { future.get() }.getOrNull() ?: return@addListener
                cameraProvider = provider

                val preview = Preview.Builder().build().also { it.setSurfaceProvider(surfaceProvider) }
                val capture = ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                    .build()
                imageCapture = capture

                provider.unbindAll()
                provider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    capture,
                )
                _isReady.value = true
            },
            ContextCompat.getMainExecutor(context),
        )
    }

    fun unbind() {
        isBound = false
        _isReady.value = false
        imageCapture = null
        cameraProvider?.unbindAll()
        cameraProvider = null
    }

    suspend fun captureStill(): CapturedPhoto {
        val capture = checkNotNull(imageCapture) { "Camera not bound — call bind() first" }
        val outputDir = File(context.filesDir, "captures").also { it.mkdirs() }
        val captureId = UUID.randomUUID().toString()
        val outputFile = File(outputDir, "$captureId.jpg")

        return suspendCancellableCoroutine { cont ->
            capture.takePicture(
                ImageCapture.OutputFileOptions.Builder(outputFile).build(),
                ContextCompat.getMainExecutor(context),
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                        cont.resume(
                            CapturedPhoto(
                                captureId    = captureId,
                                timestamp    = System.currentTimeMillis().toString(),
                                rawImagePath = outputFile.absolutePath,
                                frameId      = captureId,
                                boundingBox  = NormalizedBox(cx = 0.5f, cy = 0.5f, w = 1.0f, h = 1.0f),
                            )
                        )
                    }

                    override fun onError(exc: ImageCaptureException) {
                        cont.resumeWithException(exc)
                    }
                },
            )
        }
    }
}
