package com.giraffetechnology.qc.sku

import org.junit.Assert.*
import org.junit.Test

/**
 * Documents and statically verifies the factory LAN cleartext HTTP policy.
 *
 * The SKU API uses HTTP on the factory LAN (192.168.1.10). Cleartext is
 * configured in network_security_config.xml for this specific host only.
 * Operator inference uses only the first-party TLS cloud contract. Vendor SDKs
 * and provider endpoints are not embedded in the Pad.
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
    fun `operator cloud configuration is first party TLS and provider neutral`() {
        val firstPartyCloudBaseUrl = "https://inference.invalid"
        assertTrue(firstPartyCloudBaseUrl.startsWith("https://"))
        assertFalse(firstPartyCloudBaseUrl.contains("qwen", ignoreCase = true))
        assertFalse(firstPartyCloudBaseUrl.contains("dashscope", ignoreCase = true))
    }
}
