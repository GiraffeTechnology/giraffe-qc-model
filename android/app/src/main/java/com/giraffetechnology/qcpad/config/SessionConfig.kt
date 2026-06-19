package com.giraffetechnology.qcpad.config

object SessionConfig {
    // Inactivity timeout before auto-logout.
    // Intended to be fetched from a remote admin config in a future iteration;
    // only this object needs updating when that happens.
    const val INACTIVITY_TIMEOUT_MINUTES: Long = 15L

    // WebSocket endpoint for the Pad result feed.
    // Format: ws://<host>:<port>/ws/pad?tenant_id=<t>&sku_id=<s>
    // Override TENANT_ID and SKU_ID at runtime; host/port come from the backend.
    const val WS_HOST: String = "192.168.1.100:8765"
    const val TENANT_ID: String = "default"
    const val DEFAULT_SKU_ID: String = "SKU-001"

    fun wsUrl(skuId: String = DEFAULT_SKU_ID): String =
        "ws://$WS_HOST/ws/pad?tenant_id=$TENANT_ID&sku_id=$skuId"
}
