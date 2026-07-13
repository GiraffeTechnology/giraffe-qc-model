package com.giraffetechnology.qc.jetson

import org.json.JSONArray
import org.json.JSONObject

/**
 * Canonical JSON serialization matching Python's
 * `json.dumps(payload, sort_keys=True, separators=(",", ":"))` with default
 * `ensure_ascii=True` -- byte-for-byte, not "close enough". This MUST match
 * exactly: it is what gets HMAC-signed, and the Jetson runner
 * (`jetson_runner/app/signing.py`) recomputes the identical string on the
 * other end to verify the signature. A single stray space or escaped `/`
 * breaks every signed request.
 *
 * Verified against a real Python-computed test vector in
 * `JetsonSigningTest.kt` -- do not "simplify" this without re-checking that
 * vector still passes.
 *
 * Known limitations:
 * - Number formatting matches Python for integers/booleans/strings/null
 *   exactly, but has not been verified against Python's float repr for
 *   non-trivial floats. The current request builder (`JetsonContract.kt`)
 *   always sends `regions: []` (no floats), so this has not been a live
 *   problem -- verify against a real Python test vector before trusting it
 *   if a future change starts sending region floats.
 * - Backspace (0x08) and form-feed (0x0C) fall through to the generic
 *   `\u00XX` escape below rather than Python's named `\b`/`\f`. Neither
 *   character can occur in any field this client actually sends (device
 *   ids, point codes, base64 image data, short human-readable labels), so
 *   this divergence is inert in practice -- flagged rather than silently
 *   assumed safe.
 */
fun canonicalJson(value: Any?): String = when (value) {
    null, JSONObject.NULL -> "null"
    is JSONObject -> {
        val keys = value.keys().asSequence().sorted().toList()
        keys.joinToString(",", "{", "}") { k -> "${jsonQuote(k)}:${canonicalJson(value.get(k))}" }
    }
    is JSONArray -> {
        (0 until value.length()).joinToString(",", "[", "]") { i -> canonicalJson(value.get(i)) }
    }
    is Map<*, *> -> {
        val keys = value.keys.map { it.toString() }.sorted()
        keys.joinToString(",", "{", "}") { k -> "${jsonQuote(k)}:${canonicalJson(value[k])}" }
    }
    is List<*> -> value.joinToString(",", "[", "]") { canonicalJson(it) }
    is String -> jsonQuote(value)
    is Boolean -> value.toString()
    is Int, is Long -> value.toString()
    is Double -> formatDouble(value)
    is Float -> formatDouble(value.toDouble())
    else -> jsonQuote(value.toString())
}

/**
 * Matches Python `json.dumps` default string escaping: quotes, backslash,
 * newline/carriage-return/tab get named escapes; **forward slash is NOT
 * escaped** (unlike some JSON libraries' default); every codepoint above
 * ASCII (0x7E), plus other control chars below 0x20, is escaped as
 * `\uXXXX` because Python defaults to `ensure_ascii=True`. Iterating UTF-16
 * `Char` code units (not codepoints) matches Python's surrogate-pair
 * emission for astral characters.
 */
private fun jsonQuote(s: String): String {
    val sb = StringBuilder(s.length + 2)
    sb.append('"')
    for (c in s) {
        when (c) {
            '"' -> sb.append("\\\"")
            '\\' -> sb.append("\\\\")
            '\n' -> sb.append("\\n")
            '\r' -> sb.append("\\r")
            '\t' -> sb.append("\\t")
            else -> if (c.code < 0x20 || c.code > 0x7E) {
                sb.append("\\u").append(String.format("%04x", c.code))
            } else {
                sb.append(c)
            }
        }
    }
    sb.append('"')
    return sb.toString()
}

private fun formatDouble(d: Double): String {
    if (d == d.toLong().toDouble()) return "${d.toLong()}.0"
    return d.toString()
}
