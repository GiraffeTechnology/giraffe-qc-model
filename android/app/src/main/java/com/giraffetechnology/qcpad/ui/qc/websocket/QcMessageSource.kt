package com.giraffetechnology.qcpad.ui.qc.websocket

import com.giraffetechnology.qcpad.model.QcMessage
import kotlinx.coroutines.flow.Flow

interface QcMessageSource {
    val messages: Flow<QcMessage>
    fun connect(url: String)
    fun disconnect()
}
