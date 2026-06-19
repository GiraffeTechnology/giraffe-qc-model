package com.giraffetechnology.qcpad.ui.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.giraffetechnology.qcpad.ui.login.auth.AuthRepository
import com.giraffetechnology.qcpad.ui.login.auth.AuthResult
import com.giraffetechnology.qcpad.ui.login.auth.MockAuthRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class LoginViewModel(
    private val authRepository: AuthRepository = MockAuthRepository()
) : ViewModel() {

    private val _state = MutableStateFlow<LoginState>(LoginState.Idle)
    val state: StateFlow<LoginState> = _state

    fun login(username: String, password: String) {
        if (_state.value is LoginState.Loading) return
        _state.value = LoginState.Loading
        viewModelScope.launch {
            _state.value = when (val result = authRepository.login(username, password)) {
                is AuthResult.Success -> LoginState.Success
                is AuthResult.Failure -> LoginState.Error(result.message)
            }
        }
    }

    fun clearError() {
        if (_state.value is LoginState.Error) _state.value = LoginState.Idle
    }
}

sealed class LoginState {
    data object Idle : LoginState()
    data object Loading : LoginState()
    data object Success : LoginState()
    data class Error(val message: String) : LoginState()
}
