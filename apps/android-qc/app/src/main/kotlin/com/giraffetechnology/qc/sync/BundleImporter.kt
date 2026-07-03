package com.giraffetechnology.qc.sync

import java.io.File

/** Outcome of a bundle import attempt. */
sealed class ImportResult {
    /** New standards installed at [bundleVersion]. */
    data class Imported(val bundleVersion: Int, val skuCount: Int) : ImportResult()

    /** Same version already installed — idempotent no-op. */
    data class AlreadyInstalled(val bundleVersion: Int) : ImportResult()

    /** Rejected with an explicit reason; prior standards remain active. */
    data class Rejected(val reason: String) : ImportResult()
}

/** Audit record for every import attempt; queued to the outbox for later upload. */
data class BundleAuditRecord(
    val timestampMs: Long,
    val outcome: String,       // imported | already_installed | rejected
    val bundleVersion: Int?,
    val tenantId: String?,
    val reason: String?,
    val source: String,        // inbox | sync_pull
)

/**
 * Imports a signed standard bundle into the local [StandardStore] (Task 03).
 *
 * Order (fail-closed at every step — prior standards survive any failure):
 *   1. verify signature + checksums + manifest ([BundleVerification]),
 *   2. downgrade / idempotency check against the installed version,
 *   3. confirm every manifest-referenced photo is present in the archive,
 *   4. extract photos to app-scoped storage,
 *   5. transactional [StandardStore.installBundle].
 *
 * Both intake channels (inbox scan, sync-window pull) funnel through here.
 */
class BundleImporter(
    private val store: StandardStore,
    private val publicKey: () -> ByteArray,
    private val photoRoot: File,
    private val audit: (BundleAuditRecord) -> Unit = {},
    private val clock: () -> Long = System::currentTimeMillis,
) {

    fun import(archiveBytes: ByteArray, source: String = "inbox"): ImportResult {
        val verified = try {
            BundleVerification.verify(archiveBytes, publicKey())
        } catch (e: BundleVerifyException) {
            return reject(e.reason, null, null, source)
        }
        val manifest = verified.manifest

        // Downgrade / idempotency.
        val installed = store.installedBundleVersion(manifest.tenantId, manifest.lineScope)
        if (installed != null) {
            if (manifest.bundleVersion < installed) {
                return reject(
                    "downgrade_rejected: bundle v${manifest.bundleVersion} < installed v$installed",
                    manifest.bundleVersion, manifest.tenantId, source,
                )
            }
            if (manifest.bundleVersion == installed) {
                audit(BundleAuditRecord(clock(), "already_installed", manifest.bundleVersion,
                    manifest.tenantId, null, source))
                return ImportResult.AlreadyInstalled(manifest.bundleVersion)
            }
        }

        // Every referenced photo must be present in the (already integrity-checked) archive.
        for (sku in manifest.skus) {
            for (photo in sku.photos) {
                if (!verified.entries.containsKey(photo.path)) {
                    return reject(
                        "partial_archive_missing_photo: ${photo.path}",
                        manifest.bundleVersion, manifest.tenantId, source,
                    )
                }
            }
        }

        // Extract photos to app-scoped storage keyed by bundle version (so a failed
        // import never overwrites the live standards' photo files).
        val photoLocalPaths = HashMap<String, String>()
        val destDir = File(photoRoot, "${manifest.tenantId}/${sanitize(manifest.lineScope)}/v${manifest.bundleVersion}")
        try {
            for (sku in manifest.skus) {
                for (photo in sku.photos) {
                    val bytes = verified.entries.getValue(photo.path)
                    val outFile = File(destDir, "${sku.skuId}/${photo.filename}")
                    outFile.parentFile?.mkdirs()
                    outFile.writeBytes(bytes)
                    photoLocalPaths[photo.id] = outFile.absolutePath
                }
            }
        } catch (e: Exception) {
            return reject("photo_extract_failed: ${e.message}", manifest.bundleVersion, manifest.tenantId, source)
        }

        // Transactional install — store rolls back on any failure.
        return try {
            store.installBundle(manifest, photoLocalPaths)
            audit(BundleAuditRecord(clock(), "imported", manifest.bundleVersion,
                manifest.tenantId, null, source))
            ImportResult.Imported(manifest.bundleVersion, manifest.skus.size)
        } catch (e: Exception) {
            reject("store_install_failed: ${e.message}", manifest.bundleVersion, manifest.tenantId, source)
        }
    }

    private fun reject(reason: String, version: Int?, tenant: String?, source: String): ImportResult.Rejected {
        audit(BundleAuditRecord(clock(), "rejected", version, tenant, reason, source))
        return ImportResult.Rejected(reason)
    }

    private fun sanitize(s: String): String = s.ifEmpty { "all" }.replace(Regex("[^A-Za-z0-9_-]"), "_")
}
