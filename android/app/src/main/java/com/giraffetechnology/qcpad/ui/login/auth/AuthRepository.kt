package com.giraffetechnology.qcpad.ui.login.auth

interface AuthRepository {
    suspend fun login(username: String, password: String): AuthResult
}

sealed class AuthResult {
    data object Success : AuthResult()
    data class Failure(val message: String) : AuthResult()
}
