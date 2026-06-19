package com.giraffetechnology.qcpad.ui.qc.websocket

import com.giraffetechnology.qcpad.model.QcMessage
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow

class MockQcMessageSource : QcMessageSource {

    override val messages: Flow<QcMessage> = flow {
        delay(1_500)
        var pass = true
        while (true) {
            emit(QcMessage.DetectionResult(skuId = "SKU-DEMO-001", passed = pass))
            pass = !pass
            delay(3_000)
        }
    }

    override fun connect(url: String) {}
    override fun disconnect() {}
}
