package com.giraffetechnology.qc.operator

import com.giraffetechnology.qc.contracts.DetectionPoint
import com.giraffetechnology.qc.contracts.DetectionPointRegion
import com.giraffetechnology.qc.contracts.DetectionSeverity
import com.giraffetechnology.qc.contracts.IncidentalFindingPolicy
import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.InstalledStandardRevision
import com.giraffetechnology.qc.contracts.RequiredView
import com.giraffetechnology.qc.contracts.StandardState
import com.giraffetechnology.qc.store.InMemoryStandardStore
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.json.JSONArray

/** Offline operator task-selection logic — exact messages, offline search, confirm. */
class OperatorTaskSelectionControllerTest {

    private fun point() = DetectionPoint(
        pointCode = "center_alignment",
        label = "Center alignment",
        description = "Flower center must be aligned",
        methodHint = "visual",
        expectedValue = null,
        passCriteria = "aligned within 2mm",
        severity = DetectionSeverity.MAJOR,
        requiredView = RequiredView.FRONT,
        evidenceRequired = true,
        incidentalFindingPolicy = IncidentalFindingPolicy.FLAG_FOR_REVIEW,
        regions = listOf(DetectionPointRegion("front-photo", 0.1, 0.2, 0.3, 0.4)),
    )

    private suspend fun seed(store: InMemoryStandardStore) {
        store.installBundle(
            bundleId = "bundle-1",
            bundleVersion = 5L,
            skus = listOf(
                InstalledSku(
                    skuId = "sku-1",
                    itemNumber = "ITEM-FLOWER-001",
                    name = "Artificial Flower A",
                    state = StandardState.INSTALLED_ON_PAD.wire,
                    activeStandardRevisionId = "rev-1",
                    bundleId = "bundle-1",
                    bundleVersion = "5",
                ),
            ),
            revisions = listOf(
                InstalledStandardRevision(
                    standardRevisionId = "rev-1",
                    skuId = "sku-1",
                    revisionNo = 1,
                    state = StandardState.INSTALLED_ON_PAD.wire,
                    standardPhotoPaths = listOf("/sdcard/std/sku-1-front.jpg"),
                    detectionPoints = listOf(point()),
                    bundleId = "bundle-1",
                    bundleVersion = "5",
                ),
            ),
        )
    }

    @Test fun `empty store yields NoStandardsInstalled`() = runTest {
        val ctrl = OperatorTaskSelectionController(InMemoryStandardStore())
        ctrl.search("anything")
        assertEquals(OperatorTaskState.NoStandardsInstalled, ctrl.state.value)
    }

    @Test fun `offline search returns installed SKU with no backend`() = runTest {
        val store = InMemoryStandardStore().also { seed(it) }
        val ctrl = OperatorTaskSelectionController(store)
        ctrl.search("FLOWER")
        val s = ctrl.state.value
        assertTrue("expected Results but was $s", s is OperatorTaskState.Results)
        assertTrue((s as OperatorTaskState.Results).skus.any { it.itemNumber == "ITEM-FLOWER-001" })
    }

    @Test fun `installed-but-no-match yields SkuNotFound`() = runTest {
        val store = InMemoryStandardStore().also { seed(it) }
        val ctrl = OperatorTaskSelectionController(store)
        ctrl.search("ZZZNOTHERE")
        assertTrue(ctrl.state.value is OperatorTaskState.SkuNotFound)
    }

    @Test fun `confirm builds QcTask carrying the standard revision id, photos and points`() = runTest {
        val store = InMemoryStandardStore().also { seed(it) }
        val ctrl = OperatorTaskSelectionController(store)
        ctrl.confirm("sku-1")
        val s = ctrl.state.value
        assertTrue("expected Confirmed but was $s", s is OperatorTaskState.Confirmed)
        val task = (s as OperatorTaskState.Confirmed).task
        assertEquals("rev-1", task.activeStandardRevisionId)
        assertTrue(task.confirmedByUser)
        assertTrue(task.standardPhotos.isNotEmpty())
        assertTrue(task.qcPoints.isNotEmpty())
        assertEquals("center_alignment", task.qcPoints.first().qcPointCode)
        val regions = JSONArray(task.qcPoints.first().roiJson)
        assertEquals(1, regions.length())
        val region = regions.getJSONObject(0)
        assertEquals("front-photo", region.getString("image_id"))
        assertEquals(0.1, region.getDouble("x"), 0.0)
        assertEquals(0.2, region.getDouble("y"), 0.0)
        assertEquals(0.3, region.getDouble("w"), 0.0)
        assertEquals(0.4, region.getDouble("h"), 0.0)
    }

    @Test fun `confirm unknown SKU yields SkuNotFound`() = runTest {
        val store = InMemoryStandardStore().also { seed(it) }
        val ctrl = OperatorTaskSelectionController(store)
        ctrl.confirm("does-not-exist")
        assertTrue(ctrl.state.value is OperatorTaskState.SkuNotFound)
    }
}
