package com.giraffetechnology.qc.multimodal

/**
 * Provider selection config for the Pad multimodal QC pipeline.
 *
 * Defaults:
 *   localMnnEnabled = true      primary production path (on-device MNN)
 *   backendProxyEnabled = false  opt-in (PAD_ALLOW_BACKEND_PROXY=true)
 *   directCloudEnabled = false   PERMANENT — Pad never calls cloud directly
 *   mockEnabled = false          CI/test only
 *
 * directCloudEnabled is enforced false in init{}. Passing true throws immediately.
 */
data class MultimodalProviderConfig(
    val localMnnEnabled: Boolean = true,
    val backendProxyEnabled: Boolean = false,
    val directCloudEnabled: Boolean = false,
    val mockEnabled: Boolean = false,
    val onDeviceTimeoutMs: Long = 60_000L,
    val minPassConfidence: Float = 0.82f,
    val backendBaseUrl: String = "",
    val backendTimeoutMs: Int = 30_000,
) {
    init {
        // PAD_ALLOW_DIRECT_CLOUD must never be true. Cloud providers are server-side only.
        require(!directCloudEnabled) {
            "PAD_ALLOW_DIRECT_CLOUD must be false. The Pad never calls cloud providers directly."
        }
    }

    companion object {
        val DEFAULT = MultimodalProviderConfig()

        val TEST_MOCK = MultimodalProviderConfig(
            localMnnEnabled = false,
            backendProxyEnabled = false,
            directCloudEnabled = false,
            mockEnabled = true,
        )

        fun withBackendProxy(baseUrl: String): MultimodalProviderConfig =
            MultimodalProviderConfig(
                localMnnEnabled = true,
                backendProxyEnabled = true,
                directCloudEnabled = false,
                backendBaseUrl = baseUrl,
            )
    }
}
