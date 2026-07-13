package com.giraffetechnology.qc.admin

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Parity tests for the Pad-side mirror of the backend's fail-closed
 * `normalize_regions()` rules (src/qc_model/studio/regions.py).
 */
class RegionValidatorTest {

    private val photoIds = setOf("p1", "p2")

    @Test
    fun `empty list is valid and clears annotations`() {
        assertEquals(emptyList<Region>(), RegionValidator.normalize(emptyList(), photoIds))
    }

    @Test
    fun `valid region passes through`() {
        val region = Region("p1", 0.1f, 0.2f, 0.3f, 0.4f)
        assertEquals(listOf(region), RegionValidator.normalize(listOf(region), photoIds))
    }

    @Test
    fun `box touching the edge is valid`() {
        val region = Region("p1", 0.5f, 0.5f, 0.5f, 0.5f)
        assertEquals(listOf(region), RegionValidator.normalize(listOf(region), photoIds))
    }

    private fun assertRejected(region: Region, fragment: String) {
        try {
            RegionValidator.normalize(listOf(region), photoIds)
            throw AssertionError("expected InvalidRegionException for $region")
        } catch (e: InvalidRegionException) {
            assertTrue("message '${e.message}' should mention '$fragment'",
                e.message!!.contains(fragment))
        }
    }

    @Test
    fun `unknown image id fails closed`() =
        assertRejected(Region("nope", 0.1f, 0.1f, 0.2f, 0.2f), "not a standard photo")

    @Test
    fun `blank image id fails closed`() =
        assertRejected(Region("", 0.1f, 0.1f, 0.2f, 0.2f), "image_id is required")

    @Test
    fun `coordinate outside 0-1 fails closed`() =
        assertRejected(Region("p1", -0.1f, 0.1f, 0.2f, 0.2f), "outside [0, 1]")

    @Test
    fun `zero area fails closed`() =
        assertRejected(Region("p1", 0.1f, 0.1f, 0f, 0.2f), "positive width and height")

    @Test
    fun `box past image bounds fails closed`() =
        assertRejected(Region("p1", 0.8f, 0.1f, 0.3f, 0.2f), "past the image bounds")

    @Test
    fun `pending store keeps and clears queued regions per point`() {
        val store = PendingRegionStore()
        val regions = listOf(Region("p1", 0.1f, 0.1f, 0.2f, 0.2f))
        store.put("dp1", regions)
        assertEquals(regions, store.get("dp1"))
        assertEquals(emptyList<Region>(), store.get("dp2"))
        store.clear("dp1")
        assertEquals(emptyList<Region>(), store.get("dp1"))
    }
}
