package com.giraffetechnology.qc.sync

import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer

/**
 * Ed25519 signature verification using BouncyCastle's lightweight API.
 *
 * The public key is the raw 32-byte key (base64) shipped as an app asset
 * (`assets/qc_bundle_public_key.b64`), matching the server's
 * `public_key_b64_raw`. The lightweight API works on all Android API levels
 * (minSdk 26) and on the JVM (unit tests), independent of the platform's
 * java.security Ed25519 support (which only exists on API 33+).
 */
object Ed25519Verifier {

    /** Returns true iff [signature] is a valid Ed25519 signature of [payload]. */
    fun verify(rawPublicKey: ByteArray, payload: ByteArray, signature: ByteArray): Boolean {
        if (rawPublicKey.size != 32) return false
        return try {
            val params = Ed25519PublicKeyParameters(rawPublicKey, 0)
            val signer = Ed25519Signer()
            signer.init(false, params)
            signer.update(payload, 0, payload.size)
            signer.verifySignature(signature)
        } catch (_: Exception) {
            false
        }
    }
}
