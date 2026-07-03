package com.giraffetechnology.qc.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** Signature + checksum verification and tamper rejection (Task 03, acceptance #4/#8). */
class BundleVerificationTest {

    private val factory = TestBundleFactory()

    @Test fun `valid bundle verifies and parses`() {
        val archive = factory.build(skus = listOf(
            TestBundleFactory.Sku("sku-a", "ITEM-A", "A"),
            TestBundleFactory.Sku("sku-b", "ITEM-B", "B"),
        ))
        val verified = BundleVerification.verify(archive, factory.rawPublicKey)
        assertEquals(2, verified.manifest.skus.size)
        assertEquals(setOf("ITEM-A", "ITEM-B"), verified.manifest.skus.map { it.itemNumber }.toSet())
    }

    @Test fun `tampered manifest is rejected`() {
        val archive = factory.build(skus = listOf(TestBundleFactory.Sku("sku-a", "ITEM-A", "A")))
        val tampered = factory.tamperMember(archive, "manifest.json") {
            String(it).replace("ITEM-A", "ITEM-X").toByteArray()
        }
        val ex = assertThrows(BundleVerifyException::class.java) {
            BundleVerification.verify(tampered, factory.rawPublicKey)
        }
        // Signature covers the manifest, so the tamper trips signature verification.
        assertTrue(ex.reason.startsWith("signature") || ex.reason.startsWith("manifest_checksum"))
    }

    @Test fun `tampered photo is rejected`() {
        val archive = factory.build(skus = listOf(TestBundleFactory.Sku("sku-a", "ITEM-A", "A", photos = 1)))
        val photoName = TarGz.readEntries(archive).keys.first { it.startsWith("photos/") }
        val tampered = factory.tamperMember(archive, photoName) { it + "EVIL".toByteArray() }
        val ex = assertThrows(BundleVerifyException::class.java) {
            BundleVerification.verify(tampered, factory.rawPublicKey)
        }
        assertTrue(ex.reason.startsWith("checksum_mismatch"))
    }

    @Test fun `wrong public key is rejected`() {
        val archive = factory.build()
        val otherKey = TestBundleFactory().rawPublicKey
        val ex = assertThrows(BundleVerifyException::class.java) {
            BundleVerification.verify(archive, otherKey)
        }
        assertEquals("signature_verification_failed", ex.reason)
    }

    @Test fun `missing signature member is rejected`() {
        val entries = TarGz.readEntries(factory.build())
        entries.remove("bundle.sig")
        val ex = assertThrows(BundleVerifyException::class.java) {
            BundleVerification.verify(factory.pack(entries), factory.rawPublicKey)
        }
        assertEquals("missing_bundle.sig", ex.reason)
    }
}
