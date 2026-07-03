package com.giraffetechnology.qc.camera

import android.content.Context
import android.util.Log
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.util.UUID
import java.util.concurrent.Executors

/**
 * Secondary [CameraFrameSource] backed by the device's built-in camera via
 * CameraX [ImageAnalysis].
 *
 * Per Work Item 3 the production line uses an external USB UVC camera
 * ([UvcCameraFrameSource]); this built-in-camera source exists so end-to-end
 * verification can run on a test unit (e.g. the OPPO PKB110) that cannot host
 * the UVC camera during a given pass. Every emitted [CameraFrame] corresponds
 * to a real analyzed camera frame — nothing is synthesized.
 *
 * Frames carry no persisted image path (imagePathOrBufferRef = null); they drive
 * the live detector stream. The still image used for inference is captured
 * separately by [CameraXCaptureController].
 */
class CameraXFrameSource(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val cameraSelector: CameraSelector = CameraSelector.DEFAULT_BACK_CAMERA,
) : CameraFrameSource {

    private val _frames = MutableSharedFlow<CameraFrame>(extraBufferCapacity = 8)
    override val frames: Flow<CameraFrame> = _frames.asSharedFlow()

    private val analysisExecutor = Executors.newSingleThreadExecutor()

    @Volatile private var cameraProvider: ProcessCameraProvider? = null
    @Volatile private var analysis: ImageAnalysis? = null

    override fun start() {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val provider = runCatching { future.get() }.getOrNull() ?: run {
                Log.e(TAG, "CameraProvider unavailable")
                return@addListener
            }
            cameraProvider = provider

            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
                .also { it.setAnalyzer(analysisExecutor, ::onImage) }
            analysis = imageAnalysis

            runCatching {
                provider.unbindAll()
                provider.bindToLifecycle(lifecycleOwner, cameraSelector, imageAnalysis)
                Log.i(TAG, "CameraX frame source bound")
            }.onFailure { Log.e(TAG, "bindToLifecycle failed: ${it.message}") }
        }, ContextCompat.getMainExecutor(context))
    }

    override fun stop() {
        analysis?.clearAnalyzer()
        cameraProvider?.unbindAll()
        analysis = null
        cameraProvider = null
    }

    private fun onImage(image: ImageProxy) {
        try {
            _frames.tryEmit(
                CameraFrame(
                    frameId = UUID.randomUUID().toString(),
                    timestampMs = image.imageInfo.timestamp,
                    imagePathOrBufferRef = null,
                    widthPx = image.width,
                    heightPx = image.height,
                )
            )
        } finally {
            image.close()
        }
    }

    companion object { private const val TAG = "CameraXFrameSource" }
}
