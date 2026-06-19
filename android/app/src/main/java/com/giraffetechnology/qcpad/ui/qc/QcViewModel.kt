package com.giraffetechnology.qcpad.ui.qc

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.giraffetechnology.qcpad.config.SessionConfig
import com.giraffetechnology.qcpad.model.AggregateStatus
import com.giraffetechnology.qcpad.model.QcMessage
import com.giraffetechnology.qcpad.ui.qc.websocket.MockQcMessageSource
import com.giraffetechnology.qcpad.ui.qc.websocket.QcMessageSource
import com.giraffetechnology.qcpad.ui.qc.websocket.QcWebSocketClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class QcViewModel(
    // Swap MockQcMessageSource -> QcWebSocketClient() to connect to the real backend.
    private val messageSource: QcMessageSource = QcWebSocketClient()
) : ViewModel() {

    private val _uiState = MutableStateFlow(QcUiState())
    val uiState: StateFlow<QcUiState> = _uiState

    init {
        viewModelScope.launch {
            messageSource.messages.collect { handleMessage(it) }
        }
        messageSource.connect(SessionConfig.wsUrl())
    }

    fun requestRefresh() {
        (messageSource as? QcWebSocketClient)?.sendRefresh()
    }

    private fun handleMessage(message: QcMessage) {
        _uiState.value = when (message) {
            is QcMessage.DetectionResult -> _uiState.value.copy(
                lastResult = message,
                aggregateStatus = if (message.passed) AggregateStatus.PASS else AggregateStatus.FAIL,
                isConnected = true
            )
            is QcMessage.ConnectionLost -> _uiState.value.copy(isConnected = false)
            is QcMessage.ConnectionRestored -> _uiState.value.copy(isConnected = true)
        }
    }

    override fun onCleared() {
        super.onCleared()
        messageSource.disconnect()
    }
}

data class QcUiState(
    val lastResult: QcMessage.DetectionResult? = null,
    val aggregateStatus: AggregateStatus = AggregateStatus.UNKNOWN,
    val isConnected: Boolean = false
)
