package com.giraffetechnology.qc.sync

import com.giraffetechnology.qc.sku.Sku

/**
 * Local store of imported standards (Task 03). The Pad runs fully offline against
 * whatever standards were last imported; no code path here requires network.
 *
 * [installBundle] is all-or-nothing: on any failure the previous standards remain
 * active. A concrete SQLite implementation lives in
 * `com.giraffetechnology.qc.store.SqliteStandardStore`; unit tests drive an
 * in-memory implementation so the importer's verify/rollback logic is exercised
 * without an Android runtime.
 */
interface StandardStore {

    /** Installed bundle version for the (tenant, line) scope, or null if none. */
    fun installedBundleVersion(tenantId: String, lineScope: String): Int?

    /**
     * Transactionally replace the standards for the manifest's (tenant, line)
     * scope with the bundle's contents. [photoLocalPaths] maps BundlePhoto.id to
     * the absolute on-device path the importer already wrote. All-or-nothing.
     */
    fun installBundle(manifest: BundleManifest, photoLocalPaths: Map<String, String>)

    /** SKUs with an imported standard for this tenant (offline task selection). */
    fun listSkus(tenantId: String): List<Sku>

    fun getSku(tenantId: String, skuId: String): Sku?

    fun findByItemNumber(tenantId: String, query: String): List<Sku>
}

/** Per-scope installed-standards version info for UI indicators. */
data class StandardsVersionInfo(
    val tenantId: String,
    val lineScope: String,
    val bundleVersion: Int?,
    val skuCount: Int,
    val importedAt: Long?,
)
