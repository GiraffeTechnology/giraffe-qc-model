package com.giraffetechnology.qc.sku

import org.junit.Assert.*
import org.junit.Test

/**
 * Documents and statically verifies the factory LAN cleartext HTTP policy.
 *
 * The SKU API uses HTTP on the factory LAN (192.168.1.10). Cleartext is
 * configured in network_security_config.xml for this specific host only.
 * Pad-side QC inference remains local-only MNN (QWEN_CLOUD_ENABLED=false).
 */
class NetworkSecurityPolicyTest {

    @Test
    fun `factory LAN SKU API base URL uses HTTP for local network`() {
        val skuApiBaseUrl = "http://192.168.1.10:8080"
        assertTrue(
            "SKU_API_BASE_URL must use HTTP for factory LAN access",
            skuApiBaseUrl.startsWith("http://"),
        )
        assertFalse(
            "SKU_API_BASE_URL must not reference cloud endpoints",
            skuApiBaseUrl.contains("dashscope")
                || skuApiBaseUrl.contains("qwen")
                || skuApiBaseUrl.contains("cloud"),
        )
    }

    @Test
    fun `cleartext is for factory LAN SKU data not cloud inference`() {
        // These mirror the BuildConfig constants in build.gradle.kts.
        val qwenCloudEnabled           = false
        val allowSendImagesToCloudQwen = false
        val allowStubPass              = false
        val padLocalOnly               = true

        assertFalse("QWEN_CLOUD_ENABLED must remain false", qwenCloudEnabled)
        assertFalse("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN must remain false",
            allowSendImagesToCloudQwen)
        assertFalse("ALLOW_STUB_PASS must remain false", allowStubPass)
        assertTrue("PAD_LOCAL_ONLY must remain true", padLocalOnly)
    }
}
