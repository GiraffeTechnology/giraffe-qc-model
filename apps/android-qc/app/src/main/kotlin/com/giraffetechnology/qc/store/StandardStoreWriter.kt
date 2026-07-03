package com.giraffetechnology.qc.store

import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.InstalledStandardRevision

/**
 * Write side of the on-device standards store, separated from the read-only
 * [com.giraffetechnology.qc.contracts.SqliteStandardStore] surface the UI uses.
 * [BundleImporter] depends only on this port, so the import logic is testable
 * against an in-memory writer without any SQLite/Android runtime.
 */
interface StandardStoreWriter {

    /** Monotonic bundle version currently installed, or null if the store is empty. */
    suspend fun installedBundleVersion(): Long?

    /**
     * Persist a verified bundle's SKUs and revisions as the installed standard
     * set. Implementations MUST apply this atomically (all-or-nothing): a failed
     * import leaves the previously installed standards intact.
     */
    suspend fun installBundle(
        bundleId: String,
        bundleVersion: Long,
        skus: List<InstalledSku>,
        revisions: List<InstalledStandardRevision>,
    )
}
