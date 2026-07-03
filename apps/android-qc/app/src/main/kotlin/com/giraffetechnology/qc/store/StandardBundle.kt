package com.giraffetechnology.qc.store

import com.giraffetechnology.qc.contracts.DetectionPoint

/**
 * A standard bundle received by the Pad (S3 produces it; S5 consumes it via a
 * sync-window pull or USB sideload). This is the already-verified, in-memory
 * shape handed to [BundleImporter]; signature/checksum verification of the raw
 * archive is upstream of this type (offline-sync), so anything constructed here
 * is trusted content ready to persist.
 *
 * [bundleVersion] is the monotonic integer from the bundle manifest (PRD §7);
 * the importer rejects a downgrade.
 */
data class StandardBundle(
    val bundleId: String,
    val bundleVersion: Long,
    val skus: List<BundleSku>,
)

/** One SKU carried by a bundle, with its active revision and detection points. */
data class BundleSku(
    val skuId: String,
    val itemNumber: String,
    val name: String,
    val standardRevisionId: String,
    val revisionNo: Int,
    val standardPhotoPaths: List<String>,
    val detectionPoints: List<DetectionPoint>,
)
