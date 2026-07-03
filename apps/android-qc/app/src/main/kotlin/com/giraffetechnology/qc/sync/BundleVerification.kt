package com.giraffetechnology.qc.sync

import java.security.MessageDigest

/**
 * Verifies a standard bundle the same way — and in the same order — as the
 * server's `verify_bundle_archive` (Task 03):
 *   1. Ed25519 signature over (manifest.json bytes + "\n" + checksum.sha256 bytes),
 *   2. per-file SHA-256 checksums (manifest + every photo),
 *   3. manifest JSON parse.
 *
 * Verification runs on the OUTER envelope BEFORE any manifest content is trusted.
 * Any failure throws [BundleVerifyException] with an explicit reason and the
 * caller keeps the current standards (fail-closed).
 */
class BundleVerifyException(val reason: String, cause: Throwable? = null) :
    Exception(reason, cause)

data class VerifiedBundle(
    val manifest: BundleManifest,
    val entries: Map<String, ByteArray>,
)

object BundleVerification {

    private const val MANIFEST = "manifest.json"
    private const val CHECKSUM = "checksum.sha256"
    private const val SIGNATURE = "bundle.sig"

    fun verify(archiveBytes: ByteArray, rawPublicKey: ByteArray): VerifiedBundle {
        val entries = try {
            TarGz.readEntries(archiveBytes)
        } catch (e: Exception) {
            throw BundleVerifyException("corrupt_archive: ${e.message}", e)
        }

        val manifestBytes = entries[MANIFEST]
            ?: throw BundleVerifyException("missing_$MANIFEST")
        val checksumBytes = entries[CHECKSUM]
            ?: throw BundleVerifyException("missing_$CHECKSUM")
        val sigText = entries[SIGNATURE]?.toString(Charsets.US_ASCII)?.trim()
            ?: throw BundleVerifyException("missing_$SIGNATURE")

        // 1) signature over manifest + "\n" + checksum
        val signedPayload = manifestBytes + '\n'.code.toByte() + checksumBytes
        val signature = try {
            java.util.Base64.getMimeDecoder().decode(sigText)
        } catch (e: Exception) {
            throw BundleVerifyException("bad_signature_encoding", e)
        }
        if (!Ed25519Verifier.verify(rawPublicKey, signedPayload, signature)) {
            throw BundleVerifyException("signature_verification_failed")
        }

        // 2) per-file checksums
        val expected = parseChecksums(checksumBytes)
        if (sha256Hex(manifestBytes) != expected[MANIFEST]) {
            throw BundleVerifyException("manifest_checksum_mismatch")
        }
        for ((name, data) in entries) {
            if (name == MANIFEST || name == CHECKSUM || name == SIGNATURE) continue
            val exp = expected[name] ?: throw BundleVerifyException("file_not_in_checksum: $name")
            if (sha256Hex(data) != exp) throw BundleVerifyException("checksum_mismatch: $name")
        }

        // 3) manifest parse (only after integrity proven)
        val manifest = try {
            BundleManifestParser.parse(manifestBytes.toString(Charsets.UTF_8))
        } catch (e: Exception) {
            throw BundleVerifyException("manifest_parse_failed: ${e.message}", e)
        }
        return VerifiedBundle(manifest, entries)
    }

    private fun parseChecksums(bytes: ByteArray): Map<String, String> {
        val out = HashMap<String, String>()
        for (rawLine in bytes.toString(Charsets.UTF_8).lineSequence()) {
            val line = rawLine.trim()
            if (line.isEmpty()) continue
            val parts = line.split(Regex("\\s+"), limit = 2)
            if (parts.size != 2) throw BundleVerifyException("malformed_checksum_line")
            out[parts[1].removePrefix("*")] = parts[0].lowercase()
        }
        return out
    }

    private fun sha256Hex(data: ByteArray): String {
        val d = MessageDigest.getInstance("SHA-256").digest(data)
        return d.joinToString("") { "%02x".format(it) }
    }
}
