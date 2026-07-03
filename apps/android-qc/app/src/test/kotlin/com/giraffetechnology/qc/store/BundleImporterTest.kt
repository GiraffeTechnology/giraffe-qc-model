package com.giraffetechnology.qc.store

import com.giraffetechnology.qc.contracts.DetectionPoint
import com.giraffetechnology.qc.contracts.DetectionSeverity
import com.giraffetechnology.qc.contracts.IncidentalFindingPolicy
import com.giraffetechnology.qc.contracts.RequiredView
import com.giraffetechnology.qc.contracts.StandardState
import com.giraffetechnology.qc.contracts.hasAnyInstalledStandards
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Bundle import: populate the store, fail closed on empty / blank / downgrade. */
class BundleImporterTest {

    private fun bundleSku(skuId: String = "sku-1", rev: String = "rev-1") = BundleSku(
        skuId = skuId,
        itemNumber = "ITEM-001",
        name = "Widget",
        standardRevisionId = rev,
        revisionNo = 1,
        standardPhotoPaths = listOf("/sdcard/std/$skuId.jpg"),
        detectionPoints = listOf(
            DetectionPoint(
                pointCode = "p1",
                label = "Point 1",
                description = "d",
                methodHint = "visual",
                expectedValue = "3",
                passCriteria = "exactly 3",
                severity = DetectionSeverity.CRITICAL,
                requiredView = RequiredView.FRONT,
                evidenceRequired = true,
                incidentalFindingPolicy = IncidentalFindingPolicy.RECORD_ONLY,
            ),
        ),
    )

    @Test fun `import populates the store and stamps provenance`() = runTest {
        val store = InMemoryStandardStore()
        val result = BundleImporter(store).import(
            StandardBundle(bundleId = "b1", bundleVersion = 3L, skus = listOf(bundleSku()))
        )
        assertTrue(result is BundleImportResult.Installed)
        assertEquals(1, (result as BundleImportResult.Installed).skuCount)

        assertTrue(store.hasAnyInstalledStandards())
        val installed = store.getInstalledSku("sku-1")!!
        assertEquals("b1", installed.bundleId)
        assertEquals("3", installed.bundleVersion)
        assertEquals(StandardState.INSTALLED_ON_PAD.wire, installed.state)
        assertEquals("rev-1", installed.activeStandardRevisionId)

        val rev = store.getInstalledStandardRevision("sku-1")!!
        assertEquals("b1", rev.bundleId)
        assertEquals(1, rev.detectionPoints.size)
        assertEquals("p1", rev.detectionPoints.first().pointCode)
    }

    @Test fun `empty bundle is rejected`() = runTest {
        val store = InMemoryStandardStore()
        val result = BundleImporter(store).import(StandardBundle("b1", 1L, emptyList()))
        assertTrue(result is BundleImportResult.Rejected)
        assertFalse(store.hasAnyInstalledStandards())
    }

    @Test fun `blank sku id is rejected`() = runTest {
        val store = InMemoryStandardStore()
        val result = BundleImporter(store).import(
            StandardBundle("b1", 1L, listOf(bundleSku(skuId = "")))
        )
        assertTrue(result is BundleImportResult.Rejected)
    }

    @Test fun `downgrade is rejected and leaves newer standards intact`() = runTest {
        val store = InMemoryStandardStore()
        val importer = BundleImporter(store)
        assertTrue(importer.import(StandardBundle("b2", 5L, listOf(bundleSku()))) is BundleImportResult.Installed)

        val result = importer.import(StandardBundle("b1", 4L, listOf(bundleSku(skuId = "sku-old"))))
        assertTrue(result is BundleImportResult.Rejected)
        // Newer bundle still installed; the stale one was not applied.
        assertEquals(5L, store.installedBundleVersion())
        assertTrue(store.getInstalledSku("sku-old") == null)
    }

    @Test fun `same version is rejected as non-monotonic`() = runTest {
        val store = InMemoryStandardStore()
        val importer = BundleImporter(store)
        importer.import(StandardBundle("b1", 5L, listOf(bundleSku())))
        assertTrue(importer.import(StandardBundle("b1", 5L, listOf(bundleSku()))) is BundleImportResult.Rejected)
    }
}
