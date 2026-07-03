package com.giraffetechnology.qc.camera

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.util.Log
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Frame source for the production line's external USB UVC camera.
 *
 * This class owns the real USB-host lifecycle — device enumeration, runtime
 * permission, and hot-plug attach/detach — via [UsbManager] and a
 * [BroadcastReceiver]. When a UVC device is attached and permission is granted
 * it opens the device and hands it to the UVC streaming layer; on detach it
 * tears the stream down.
 *
 * ## Frame decode seam (integration point)
 * Decoding UVC isochronous transfers (MJPEG/YUV) into [CameraFrame]s requires a
 * native UVC implementation (UVCCamera / saki4510t lineage or an equivalent
 * USB-host UVC stack). That native decoder is provided at device-integration
 * time and pushes decoded frames through [onDecodedFrame]. Until it is attached
 * this source emits NO frames — it never fabricates frames, so downstream
 * consumers stay fail-closed rather than acting on invented data.
 *
 * @param frameSink invoked with the opened [UsbDevice] when permission is
 *   granted; the integrator wires the native UVC decoder here and calls
 *   [onDecodedFrame] for each real frame. Null in builds where the decoder is
 *   not yet linked (the USB lifecycle still runs; no frames are emitted).
 */
class UvcCameraFrameSource(
    private val context: Context,
    private val frameSink: ((UsbDevice) -> Unit)? = null,
) : CameraFrameSource {

    private val _frames = MutableSharedFlow<CameraFrame>(extraBufferCapacity = 8)
    override val frames: Flow<CameraFrame> = _frames.asSharedFlow()

    /** Observable connection state so the UI can reflect camera presence. */
    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()

    private val usbManager: UsbManager =
        context.getSystemService(Context.USB_SERVICE) as UsbManager

    @Volatile private var openDevice: UsbDevice? = null

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            when (intent.action) {
                ACTION_USB_PERMISSION -> {
                    val device = intent.usbDevice()
                    val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    if (granted && device != null) {
                        onPermissionGranted(device)
                    } else {
                        Log.w(TAG, "USB permission denied for ${device?.deviceName}")
                    }
                }
                UsbManager.ACTION_USB_DEVICE_ATTACHED -> {
                    val device = intent.usbDevice() ?: return
                    if (isUvc(device)) requestPermission(device)
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    val device = intent.usbDevice() ?: return
                    if (device.deviceId == openDevice?.deviceId) onDetached()
                }
            }
        }
    }

    override fun start() {
        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        registerReceiverCompat(filter)
        // Adopt an already-connected UVC device (attach event predates start()).
        usbManager.deviceList.values.firstOrNull { isUvc(it) }?.let { requestPermission(it) }
    }

    override fun stop() {
        runCatching { context.unregisterReceiver(receiver) }
        onDetached()
    }

    private fun requestPermission(device: UsbDevice) {
        if (usbManager.hasPermission(device)) {
            onPermissionGranted(device)
            return
        }
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S)
            PendingIntent.FLAG_IMMUTABLE else 0
        val pi = PendingIntent.getBroadcast(
            context, 0, Intent(ACTION_USB_PERMISSION).setPackage(context.packageName), flags,
        )
        usbManager.requestPermission(device, pi)
    }

    private fun onPermissionGranted(device: UsbDevice) {
        openDevice = device
        _connected.value = true
        Log.i(TAG, "UVC device ready: ${device.deviceName}")
        // Hand the opened device to the native UVC decoder, which will call
        // onDecodedFrame() for each real frame. No decoder → no frames.
        frameSink?.invoke(device)
    }

    private fun onDetached() {
        if (openDevice != null) Log.i(TAG, "UVC device detached")
        openDevice = null
        _connected.value = false
    }

    /**
     * Entry point for the native UVC decoder to publish a real, decoded frame.
     * Frames are only ever emitted through this path — never synthesized.
     */
    fun onDecodedFrame(frame: CameraFrame) {
        _frames.tryEmit(frame)
    }

    private fun isUvc(device: UsbDevice): Boolean {
        for (i in 0 until device.interfaceCount) {
            val cls = device.getInterface(i).interfaceClass
            // UVC advertises USB Video Class (0x0E) on at least one interface.
            if (cls == UsbConstants.USB_CLASS_VIDEO) return true
        }
        return false
    }

    private fun registerReceiverCompat(filter: IntentFilter) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            context.registerReceiver(receiver, filter)
        }
    }

    private fun Intent.usbDevice(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
        } else {
            @Suppress("DEPRECATION")
            getParcelableExtra(UsbManager.EXTRA_DEVICE)
        }

    companion object {
        private const val TAG = "UvcCameraFrameSource"
        private const val ACTION_USB_PERMISSION = "com.giraffetechnology.qc.USB_PERMISSION"
    }
}
