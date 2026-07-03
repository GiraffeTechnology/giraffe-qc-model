package com.giraffetechnology.qc.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** Importer: idempotency, downgrade rejection, rollback, fail-closed (Task 03, acceptance #8). */
class BundleImporterTest {

    @get:Rule val tmp = TemporaryFolder()

    private val factory = TestBundleFactory()

    private fun importer(store: StandardStore, audits: MutableList<BundleAuditRecord>) =
        BundleImporter(
            store = store,
            publicKey = { factory.rawPublicKey },
            photoRoot = tmp.newFolder("photos-${System.nanoTime()}"),
            audit = { audits.add(it) },
        )

    @Test fun `import installs standards and extracts photos`() {
        val store = InMemoryStandardStore()
        val audits = mutableListOf<BundleAuditRecord>()
        val archive = factory.build(bundleVersion = 1, skus = listOf(
            TestBundleFactory.Sku("sku-a", "ITEM-A", "A", points = 2, photos = 1),
        ))
        val result = importer(store, audits).import(archive)
        assertTrue(result is ImportResult.Imported)
        assertEquals(1, store.installedBundleVersion("default", ""))
        val sku = store.getSku("default", "sku-a")!!
        assertEquals(2, sku.detectionPoints.size)
        assertEquals(1, sku.standardPhotos.size)
        assertTrue(java.io.File(sku.standardPhotos[0].localPath).exists())
        assertEquals("imported", audits.single().outcome)
    }

    @Test fun `re-importing same version is idempotent no-op`() {
        val store = InMemoryStandardStore()
        val archive = factory.build(bundleVersion = 3)
        importer(store, mutableListOf()).import(archive)
        val second = importer(store, mutableListOf()).import(archive)
        assertTrue(second is ImportResult.AlreadyInstalled)
        assertEquals(3, store.installedBundleVersion("default", ""))
    }

    @Test fun `downgrade is rejected and prior standards intact`() {
        val store = InMemoryStandardStore()
        importer(store, mutableListOf()).import(factory.build(bundleVersion = 5,
            skus = listOf(TestBundleFactory.Sku("sku-a", "ITEM-A", "A"))))
        val older = factory.build(bundleVersion = 4,
            skus = listOf(TestBundleFactory.Sku("sku-z", "ITEM-Z", "Z")))
        val audits = mutableListOf<BundleAuditRecord>()
        val result = importer(store, audits).import(older)
        assertTrue(result is ImportResult.Rejected)
        assertTrue((result as ImportResult.Rejected).reason.startsWith("downgrade_rejected"))
        // Prior standards (v5) untouched.
        assertEquals(5, store.installedBundleVersion("default", ""))
        assertEquals("ITEM-A", store.getSku("default", "sku-a")!!.itemNumber)
        assertEquals(null, store.getSku("default", "sku-z"))
    }

    @Test fun `tampered bundle rejected and prior standards intact`() {
        val store = InMemoryStandardStore()
        importer(store, mutableListOf()).import(factory.build(bundleVersion = 1,
            skus = listOf(TestBundleFactory.Sku("sku-a", "ITEM-A", "A"))))
        val v2 = factory.build(bundleVersion = 2, skus = listOf(TestBundleFactory.Sku("sku-a", "ITEM-A2", "A2")))
        val tampered = factory.tamperMember(v2, "manifest.json") { String(it).replace("ITEM-A2", "HACK").toByteArray() }
        val result = importer(store, mutableListOf()).import(tampered)
        assertTrue(result is ImportResult.Rejected)
        assertEquals(1, store.installedBundleVersion("default", ""))
        assertEquals("ITEM-A", store.getSku("default", "sku-a")!!.itemNumber)
    }

    @Test fun `store failure rolls back to previous standards`() {
        val store = InMemoryStandardStore()
        importer(store, mutableListOf()).import(factory.build(bundleVersion = 1,
            skus = listOf(TestBundleFactory.Sku("sku-a", "ITEM-A", "A"))))
        store.failOnInstall = true
        val v2 = factory.build(bundleVersion = 2, skus = listOf(TestBundleFactory.Sku("sku-b", "ITEM-B", "B")))
        val result = importer(store, mutableListOf()).import(v2)
        assertTrue(result is ImportResult.Rejected)
        assertTrue((result as ImportResult.Rejected).reason.startsWith("store_install_failed"))
        // Rolled back: v1 standards remain.
        assertEquals(1, store.installedBundleVersion("default", ""))
        assertEquals("ITEM-A", store.getSku("default", "sku-a")!!.itemNumber)
        assertEquals(null, store.getSku("default", "sku-b"))
    }
}
