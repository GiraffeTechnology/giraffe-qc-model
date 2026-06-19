package com.giraffetechnology.qcpad.ui.qc.camera

import android.view.Surface

interface CameraSource {
    val isConnected: Boolean
    fun attach(surface: Surface)
    fun detach()
}
