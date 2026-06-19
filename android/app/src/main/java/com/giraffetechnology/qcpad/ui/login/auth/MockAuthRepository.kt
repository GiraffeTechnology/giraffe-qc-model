package com.giraffetechnology.qcpad.ui.login.auth

import kotlinx.coroutines.delay

class MockAuthRepository : AuthRepository {
    override suspend fun login(username: String, password: String): AuthResult {
        delay(800)
        return if (username.isNotBlank() && password.isNotBlank()) {
            AuthResult.Success
        } else {
            AuthResult.Failure("Username and password are required")
        }
    }
}
