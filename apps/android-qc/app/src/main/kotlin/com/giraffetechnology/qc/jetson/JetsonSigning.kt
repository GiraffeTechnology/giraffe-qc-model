package com.giraffetechnology.qc.jetson

import org.json.JSONObject
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Per-pair request signing -- the Pad-side counterpart to
 * `jetson_runner/app/signing.py`. HMAC-SHA256 over [canonicalJson] of the
 * request body, hex-encoded lowercase. `pairKey` is the per-pair secret
 * handed back by `/pair/usb` or `/pair/wifi` at pairing time -- never a
 * global/shared secret.
 */
fun signJetsonRequest(pairKey: String, request: JSONObject): String {
    val canonical = canonicalJson(request).toByteArray(Charsets.UTF_8)
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(pairKey.toByteArray(Charsets.UTF_8), "HmacSHA256"))
    val digest = mac.doFinal(canonical)
    val sb = StringBuilder(digest.size * 2)
    for (b in digest) sb.append(String.format("%02x", b))
    return sb.toString()
}
