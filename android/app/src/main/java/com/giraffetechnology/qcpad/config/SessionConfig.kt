package com.giraffetechnology.qcpad.config

object SessionConfig {
    // Inactivity timeout before auto-logout.
    // Intended to be fetched from a remote admin config in a future iteration;
    // only this object needs updating when that happens.
    const val INACTIVITY_TIMEOUT_MINUTES: Long = 15L

    // WebSocket endpoint — override when backend address is known.
    const val WS_URL: String = "ws://192.168.1.100:8765/qc"
}
