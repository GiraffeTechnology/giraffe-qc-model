package com.giraffetechnology.qc.admin

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class AdminLoginState {
    object Idle : AdminLoginState()
    object Loading : AdminLoginState()
    data class LoggedIn(val identity: AdminIdentity) : AdminLoginState()
    /** Carries an i18n key plus optional raw backend detail. */
    data class Error(val messageKey: String, val detail: String? = null) : AdminLoginState()
}

/**
 * Admin login / identity binding (WS3 item 1). A successful login binds the
 * administrator identity onto the shared [AdminApiClient]; every subsequent
 * admin action (publish, assign, final decision, …) carries that identity in
 * its `*_by` fields, so the audit trail always names the acting admin.
 */
class AdminLoginController(private val client: AdminApiClient) {

    private val _state = MutableStateFlow<AdminLoginState>(AdminLoginState.Idle)
    val state: StateFlow<AdminLoginState> = _state.asStateFlow()

    fun login(username: String, password: String, tenantId: String) {
        if (username.isBlank() || password.isBlank()) {
            _state.value = AdminLoginState.Error("admin.login.error.missing_fields")
            return
        }
        _state.value = AdminLoginState.Loading
        _state.value = when (val result = client.login(username.trim(), password, tenantId.trim())) {
            is AdminApiResult.Ok -> AdminLoginState.LoggedIn(result.value)
            is AdminApiResult.Error ->
                if (result.httpCode == 401) {
                    AdminLoginState.Error("admin.login.error.invalid", result.message)
                } else {
                    AdminLoginState.Error("admin.login.error.network", result.message)
                }
        }
    }

    fun logout() {
        client.logout()
        _state.value = AdminLoginState.Idle
    }
}
