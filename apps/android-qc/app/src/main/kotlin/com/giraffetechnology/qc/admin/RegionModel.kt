package com.giraffetechnology.qc.admin

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Region annotation on a standard photo — the exact backend data model of
 * `set_detection_point_regions()` (src/qc_model/studio/regions.py): a
 * normalized bounding box `{image_id, x, y, w, h}` with 0–1 coordinates,
 * top-left origin, bounding box only. WS6b integrates on top of this model
 * after merge, so the shape must not drift.
 */
data class Region(
    val imageId: String,
    val x: Float,
    val y: Float,
    val w: Float,
    val h: Float,
)

/** Validation error mirroring the backend's fail-closed InvalidRegion. */
class InvalidRegionException(message: String) : IllegalArgumentException(message)

object RegionValidator {

    /**
     * Validate + canonicalize regions against a set of valid photo ids.
     * Mirrors `normalize_regions()` fail-closed rules:
     * - imageId must reference a standard photo of the SKU,
     * - all coordinates in [0, 1],
     * - positive area,
     * - box must stay inside the image (x+w <= 1, y+h <= 1).
     * An empty list is valid (clears the annotation).
     */
    fun normalize(regions: List<Region>, validImageIds: Set<String>): List<Region> {
        regions.forEachIndexed { i, r ->
            if (r.imageId.isBlank()) {
                throw InvalidRegionException("region[$i].image_id is required")
            }
            if (r.imageId !in validImageIds) {
                throw InvalidRegionException(
                    "region[$i].image_id '${r.imageId}' is not a standard photo of this SKU"
                )
            }
            listOf("x" to r.x, "y" to r.y, "w" to r.w, "h" to r.h).forEach { (key, value) ->
                if (value.isNaN() || value < 0f || value > 1f) {
                    throw InvalidRegionException("region[$i].$key=$value is outside [0, 1]")
                }
            }
            if (r.w <= 0f || r.h <= 0f) {
                throw InvalidRegionException("region[$i] must have positive width and height")
            }
            if (r.x + r.w > 1f + 1e-6f || r.y + r.h > 1f + 1e-6f) {
                throw InvalidRegionException("region[$i] extends past the image bounds")
            }
        }
        return regions
    }
}

/**
 * In-memory queue of regions drawn on the Pad that could not be persisted yet.
 *
 * TODO(backend-pending: docs/api-contracts/standard-authoring-regions.md):
 * WS6 is adding the HTTP route for `set_detection_point_regions()`. Until it
 * lands, validated regions are held here (keyed by detection point id) so the
 * admin's drawing work is not lost within a session, and the UI shows an
 * explicit "pending backend" state — nothing pretends the save reached the
 * server.
 */
class PendingRegionStore {
    private val _pending = MutableStateFlow<Map<String, List<Region>>>(emptyMap())
    val pending: StateFlow<Map<String, List<Region>>> = _pending.asStateFlow()

    fun put(detectionPointId: String, regions: List<Region>) {
        _pending.value = _pending.value + (detectionPointId to regions)
    }

    fun get(detectionPointId: String): List<Region> =
        _pending.value[detectionPointId] ?: emptyList()

    fun clear(detectionPointId: String) {
        _pending.value = _pending.value - detectionPointId
    }
}
