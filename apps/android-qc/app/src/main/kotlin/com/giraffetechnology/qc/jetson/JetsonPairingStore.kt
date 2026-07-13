package com.giraffetechnology.qc.jetson

import android.content.Context
import java.util.UUID

/**
 * Read/write view of the current Jetson pairing. [JetsonPairingStore] is the
 * real, `SharedPreferences`-backed implementation; JVM unit tests use an
 * in-memory fake (mirrors this codebase's `OutboxStore`/`AndroidSqliteOutboxStore`/
 * `InMemoryOutboxStore` split) since plain JVM tests can't touch
 * `Context.getSharedPreferences`.
 */
interface JetsonPairingRepository {
    val padDeviceId: String
    val padPubkey: String
    val jetsonHost: String?
    val jetsonPort: Int
    val jetsonDeviceId: String?
    val pairKey: String?
    val pairingPath: String?
    val isPaired: Boolean

    fun savePairing(host: String, port: Int, jetsonDeviceId: String, pairKey: String, pairingPath: String)
    fun clearPairing()
}

/**
 * Persists the current Jetson pairing across app restarts. Pairing is a
 * physical/one-time act (USB cable or Wi-Fi window + fingerprint, per
 * `docs/jetson-headless-pairing.md`) -- losing it on every cold start would
 * force a re-pair every time the Pad restarts, which defeats "floor first,
 * sync later". Backed by a private `SharedPreferences` file, not the DB (no
 * DB on this Pad edition's inference path).
 *
 * `padDeviceId` is generated once and kept stable for the life of the
 * install -- the Jetson binds 1:1 to a `pad_device_id`, so a device id that
 * changed on every launch would look like a constant stream of re-pairs.
 */
class JetsonPairingStore(context: Context) : JetsonPairingRepository {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    override val padDeviceId: String
        get() = prefs.getString(KEY_PAD_DEVICE_ID, null) ?: generateAndStorePadDeviceId()

    override val padPubkey: String
        get() = prefs.getString(KEY_PAD_PUBKEY, null) ?: generateAndStorePadPubkey()

    override val jetsonHost: String? get() = prefs.getString(KEY_HOST, null)
    override val jetsonPort: Int get() = prefs.getInt(KEY_PORT, DEFAULT_PORT)
    override val jetsonDeviceId: String? get() = prefs.getString(KEY_JETSON_DEVICE_ID, null)
    override val pairKey: String? get() = prefs.getString(KEY_PAIR_KEY, null)
    override val pairingPath: String? get() = prefs.getString(KEY_PAIRING_PATH, null)

    override val isPaired: Boolean get() = jetsonHost != null && pairKey != null && jetsonDeviceId != null

    override fun savePairing(host: String, port: Int, jetsonDeviceId: String, pairKey: String, pairingPath: String) {
        prefs.edit()
            .putString(KEY_HOST, host)
            .putInt(KEY_PORT, port)
            .putString(KEY_JETSON_DEVICE_ID, jetsonDeviceId)
            .putString(KEY_PAIR_KEY, pairKey)
            .putString(KEY_PAIRING_PATH, pairingPath)
            .apply()
    }

    /** Drops the local pairing record (e.g. after the Jetson reports re-pair to someone else). */
    override fun clearPairing() {
        prefs.edit()
            .remove(KEY_HOST).remove(KEY_PORT).remove(KEY_JETSON_DEVICE_ID)
            .remove(KEY_PAIR_KEY).remove(KEY_PAIRING_PATH)
            .apply()
    }

    private fun generateAndStorePadDeviceId(): String {
        val id = "pad-${UUID.randomUUID().toString().replace("-", "").take(12)}"
        prefs.edit().putString(KEY_PAD_DEVICE_ID, id).apply()
        return id
    }

    private fun generateAndStorePadPubkey(): String {
        // Stand-in "public key", same spirit as the mock Jetson identity
        // generator (src/qc_model/jetson/identity.py) -- a stable per-install
        // token, not a real asymmetric keypair. Production hardening (real
        // keypair / mTLS) is out of scope for this scaffold.
        val key = "padpub-${UUID.randomUUID().toString().replace("-", "")}"
        prefs.edit().putString(KEY_PAD_PUBKEY, key).apply()
        return key
    }

    companion object {
        private const val PREFS_NAME = "jetson_pairing"
        private const val KEY_PAD_DEVICE_ID = "pad_device_id"
        private const val KEY_PAD_PUBKEY = "pad_pubkey"
        private const val KEY_HOST = "jetson_host"
        private const val KEY_PORT = "jetson_port"
        private const val KEY_JETSON_DEVICE_ID = "jetson_device_id"
        private const val KEY_PAIR_KEY = "pair_key"
        private const val KEY_PAIRING_PATH = "pairing_path"
        const val DEFAULT_PORT = 8600
    }
}
