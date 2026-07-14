package com.giraffetechnology.qc.operator.cloud

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.util.Base64

interface CloudDeviceSigner {
    fun sign(input: ByteArray): String
}

/** Device key never leaves Android Keystore. Provisioning registers its public key. */
class AndroidKeystoreEd25519Signer(private val alias: String = "giraffe-operator-cloud-v1") : CloudDeviceSigner {
    override fun sign(input: ByteArray): String {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (!store.containsAlias(alias)) {
            val generator = KeyPairGenerator.getInstance("Ed25519", "AndroidKeyStore")
            generator.initialize(
                KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                    .setDigests(KeyProperties.DIGEST_NONE)
                    .build()
            )
            generator.generateKeyPair()
        }
        val key = requireNotNull(store.getKey(alias, null)) { "device_signing_key_unavailable" }
        val signature = Signature.getInstance("Ed25519").apply { initSign(key as java.security.PrivateKey); update(input) }
        return Base64.getEncoder().encodeToString(signature.sign())
    }
}
