package com.giraffetechnology.qc.jetson

/** JVM-testable fake -- mirrors `InMemoryOutboxStore`/`InMemoryStandardStore`. */
class InMemoryJetsonPairingStore(
    override val padDeviceId: String = "pad-test-device",
    override val padPubkey: String = "padpub-test",
) : JetsonPairingRepository {
    override var jetsonHost: String? = null
        private set
    override var jetsonPort: Int = JetsonPairingStore.DEFAULT_PORT
        private set
    override var jetsonDeviceId: String? = null
        private set
    override var pairKey: String? = null
        private set
    override var pairingPath: String? = null
        private set

    override val isPaired: Boolean get() = jetsonHost != null && pairKey != null && jetsonDeviceId != null

    override fun savePairing(host: String, port: Int, jetsonDeviceId: String, pairKey: String, pairingPath: String) {
        this.jetsonHost = host
        this.jetsonPort = port
        this.jetsonDeviceId = jetsonDeviceId
        this.pairKey = pairKey
        this.pairingPath = pairingPath
    }

    override fun clearPairing() {
        jetsonHost = null
        jetsonDeviceId = null
        pairKey = null
        pairingPath = null
    }
}
