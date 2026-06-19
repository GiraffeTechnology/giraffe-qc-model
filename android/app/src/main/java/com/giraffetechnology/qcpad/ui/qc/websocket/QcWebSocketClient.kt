package com.giraffetechnology.qcpad.ui.qc.websocket

import com.giraffetechnology.qcpad.model.QcMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class QcWebSocketClient : QcMessageSource {

    private val _messages = MutableSharedFlow<QcMessage>(extraBufferCapacity = 64)
    override val messages: Flow<QcMessage> = _messages

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var currentUrl: String? = null
    private var reconnectJob: Job? = null

    override fun connect(url: String) {
        currentUrl = url
        reconnectJob?.cancel()
        val request = Request.Builder().url(url).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                _messages.tryEmit(QcMessage.ConnectionRestored)
            }

            override fun onMessage(ws: WebSocket, text: String) {
                parseMessage(text)?.let { _messages.tryEmit(it) }
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                _messages.tryEmit(QcMessage.ConnectionLost)
                scheduleReconnect()
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                if (code != 1000) {
                    _messages.tryEmit(QcMessage.ConnectionLost)
                    scheduleReconnect()
                }
            }
        })
    }

    // Update only this function when the backend JSON schema is finalised.
    private fun parseMessage(json: String): QcMessage? = runCatching {
        val obj = JSONObject(json)
        QcMessage.DetectionResult(
            skuId = obj.getString("sku_id"),
            passed = obj.getBoolean("passed"),
            referenceImageUrl = obj.optString("reference_url").takeIf { it.isNotEmpty() }
        )
    }.getOrNull()

    private fun scheduleReconnect(backoffMs: Long = 3_000) {
        val url = currentUrl ?: return
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            delay(backoffMs)
            connect(url)
        }
    }

    override fun disconnect() {
        reconnectJob?.cancel()
        webSocket?.close(1000, "Disconnect")
        webSocket = null
        currentUrl = null
    }
}
