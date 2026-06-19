package com.giraffetechnology.qcpad.ui.qc.camera

import android.content.Context
import android.hardware.usb.UsbDevice
import android.view.Surface
import com.serenegiant.usb.USBMonitor
import com.serenegiant.usb.UVCCamera
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

class UvcCameraSource(private val context: Context) : CameraSource {

    private var usbMonitor: USBMonitor? = null
    private var uvcCamera: UVCCamera? = null
    private var activeSurface: Surface? = null

    private val _isConnected = MutableStateFlow(false)
    override val isConnected: Boolean get() = _isConnected.value
    val connectionState: StateFlow<Boolean> = _isConnected

    fun startMonitoring(onConnected: () -> Unit, onDisconnected: () -> Unit) {
        usbMonitor = USBMonitor(context, object : USBMonitor.OnDeviceConnectListener {
            override fun onAttach(device: UsbDevice?) {
                usbMonitor?.requestPermission(device)
            }

            override fun onConnect(
                device: UsbDevice?,
                ctrlBlock: USBMonitor.UsbControlBlock?,
                createNew: Boolean
            ) {
                openCamera(ctrlBlock)
                _isConnected.value = true
                onConnected()
            }

            override fun onDisconnect(
                device: UsbDevice?,
                ctrlBlock: USBMonitor.UsbControlBlock?
            ) {
                releaseCamera()
                _isConnected.value = false
                onDisconnected()
            }

            override fun onDettach(device: UsbDevice?) {
                releaseCamera()
                _isConnected.value = false
                onDisconnected()
            }

            override fun onCancel(device: UsbDevice?) {}
        })
        usbMonitor?.register()
    }

    private fun openCamera(ctrlBlock: USBMonitor.UsbControlBlock?) {
        uvcCamera = UVCCamera().apply {
            open(ctrlBlock)
            try {
                setPreviewSize(
                    UVCCamera.DEFAULT_PREVIEW_WIDTH,
                    UVCCamera.DEFAULT_PREVIEW_HEIGHT
                )
            } catch (_: IllegalArgumentException) {
                // Device doesn't support the default size; stream at its native resolution.
            }
            activeSurface?.let { setPreviewDisplay(it) }
            startPreview()
        }
    }

    private fun releaseCamera() {
        uvcCamera?.run {
            stopPreview()
            destroy()
        }
        uvcCamera = null
    }

    override fun attach(surface: Surface) {
        activeSurface = surface
        uvcCamera?.setPreviewDisplay(surface)
    }

    override fun detach() {
        activeSurface = null
    }

    fun destroy() {
        releaseCamera()
        usbMonitor?.unregister()
        usbMonitor?.destroy()
        usbMonitor = null
    }
}
