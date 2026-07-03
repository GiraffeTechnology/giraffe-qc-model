package com.giraffetechnology.qc.store

import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.InstalledStandardRevision
import com.giraffetechnology.qc.contracts.SqliteStandardStore

/**
 * Pure JVM implementation of the store read + write ports, used to unit-test the
 * offline task-selection controller and bundle importer without a SQLite/Android
 * runtime. Mirrors [AndroidSqliteStandardStore]'s full-replace install semantics.
 */
class InMemoryStandardStore : SqliteStandardStore, StandardStoreWriter {
    private var version: Long? = null
    private val skus = LinkedHashMap<String, InstalledSku>()
    private val revisionsBySku = LinkedHashMap<String, InstalledStandardRevision>()

    override suspend fun searchInstalledSku(query: String): List<InstalledSku> {
        val q = query.trim()
        return skus.values.filter {
            it.itemNumber.contains(q, ignoreCase = true) || it.name.contains(q, ignoreCase = true)
        }
    }

    override suspend fun getInstalledSku(skuId: String): InstalledSku? = skus[skuId]

    override suspend fun getInstalledStandardRevision(skuId: String): InstalledStandardRevision? =
        revisionsBySku[skuId]

    override suspend fun installedBundleVersion(): Long? = version

    override suspend fun installBundle(
        bundleId: String,
        bundleVersion: Long,
        skus: List<InstalledSku>,
        revisions: List<InstalledStandardRevision>,
    ) {
        this.skus.clear()
        this.revisionsBySku.clear()
        skus.forEach { this.skus[it.skuId] = it }
        revisions.forEach { this.revisionsBySku[it.skuId] = it }
        version = bundleVersion
    }
}
