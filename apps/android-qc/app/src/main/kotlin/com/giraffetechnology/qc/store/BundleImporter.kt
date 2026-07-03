package com.giraffetechnology.qc.store

import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.InstalledStandardRevision
import com.giraffetechnology.qc.contracts.StandardState

/**
 * Imports a verified [StandardBundle] into the on-device store (S5 §14).
 *
 * Fail-closed rules:
 * - A bundle with no SKUs, or any SKU/revision with a blank id, is rejected —
 *   never install a partial/garbage standard set.
 * - A downgrade (bundle version <= the installed version) is rejected so a stale
 *   sideloaded bundle cannot overwrite newer standards.
 * - The underlying [StandardStoreWriter.installBundle] is atomic, so a rejected
 *   or failed import leaves the previously installed standards untouched.
 */
class BundleImporter(private val writer: StandardStoreWriter) {

    suspend fun import(bundle: StandardBundle): BundleImportResult {
        if (bundle.bundleId.isBlank()) {
            return BundleImportResult.Rejected("Bundle id is blank")
        }
        if (bundle.skus.isEmpty()) {
            return BundleImportResult.Rejected("Bundle contains no SKUs")
        }
        bundle.skus.forEach { s ->
            if (s.skuId.isBlank() || s.standardRevisionId.isBlank()) {
                return BundleImportResult.Rejected("Bundle SKU has a blank id")
            }
        }

        val installed = writer.installedBundleVersion()
        if (installed != null && bundle.bundleVersion <= installed) {
            return BundleImportResult.Rejected(
                "Bundle version ${bundle.bundleVersion} is not newer than installed $installed"
            )
        }

        val installedState = StandardState.INSTALLED_ON_PAD.wire
        val version = bundle.bundleVersion.toString()

        val skus = bundle.skus.map { s ->
            InstalledSku(
                skuId = s.skuId,
                itemNumber = s.itemNumber,
                name = s.name,
                state = installedState,
                activeStandardRevisionId = s.standardRevisionId,
                bundleId = bundle.bundleId,
                bundleVersion = version,
            )
        }
        val revisions = bundle.skus.map { s ->
            InstalledStandardRevision(
                standardRevisionId = s.standardRevisionId,
                skuId = s.skuId,
                revisionNo = s.revisionNo,
                state = installedState,
                standardPhotoPaths = s.standardPhotoPaths,
                detectionPoints = s.detectionPoints,
                bundleId = bundle.bundleId,
                bundleVersion = version,
            )
        }

        writer.installBundle(bundle.bundleId, bundle.bundleVersion, skus, revisions)
        return BundleImportResult.Installed(skuCount = skus.size, bundleVersion = bundle.bundleVersion)
    }
}

sealed class BundleImportResult {
    data class Installed(val skuCount: Int, val bundleVersion: Long) : BundleImportResult()
    data class Rejected(val reason: String) : BundleImportResult()
}
