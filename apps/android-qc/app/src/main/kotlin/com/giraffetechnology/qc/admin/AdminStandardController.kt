package com.giraffetechnology.qc.admin

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

sealed class AdminUploadState {
    object Idle : AdminUploadState()
    object Uploading : AdminUploadState()
    data class Uploaded(val photoId: String) : AdminUploadState()
    data class Error(val message: String) : AdminUploadState()
}

sealed class AdminPointEditState {
    object Idle : AdminPointEditState()
    object Saving : AdminPointEditState()
    data class Saved(val pointId: String) : AdminPointEditState()
    data class Error(val message: String) : AdminPointEditState()
}

sealed class AdminRegionSaveState {
    object Idle : AdminRegionSaveState()
    data class Invalid(val message: String) : AdminRegionSaveState()
    /**
     * Regions validated and queued locally; server write awaits WS6's route.
     * This state is surfaced verbatim in the UI so a pending save can never be
     * mistaken for a completed one.
     */
    data class QueuedPendingBackend(val detectionPointId: String, val count: Int) : AdminRegionSaveState()
    data class SavedToServer(val detectionPointId: String) : AdminRegionSaveState()
}

/**
 * Standard authoring on the Pad (WS3 items 3–5): reference photo / process-card
 * upload, detection point input/edit, and region drawing with the backend's
 * exact region data model.
 */
class AdminStandardController(
    private val client: AdminApiClient,
    private val pendingRegions: PendingRegionStore = PendingRegionStore(),
) {
    private val _uploadState = MutableStateFlow<AdminUploadState>(AdminUploadState.Idle)
    val uploadState: StateFlow<AdminUploadState> = _uploadState.asStateFlow()

    private val _pointState = MutableStateFlow<AdminPointEditState>(AdminPointEditState.Idle)
    val pointState: StateFlow<AdminPointEditState> = _pointState.asStateFlow()

    private val _regionState = MutableStateFlow<AdminRegionSaveState>(AdminRegionSaveState.Idle)
    val regionState: StateFlow<AdminRegionSaveState> = _regionState.asStateFlow()

    val pendingRegionsByPoint: StateFlow<Map<String, List<Region>>> = pendingRegions.pending

    fun uploadPhoto(
        skuId: String,
        fileName: String,
        mimeType: String,
        bytes: ByteArray,
        viewType: String?,
    ) {
        if (bytes.isEmpty()) {
            _uploadState.value = AdminUploadState.Error("empty file")
            return
        }
        _uploadState.value = AdminUploadState.Uploading
        _uploadState.value =
            when (val r = client.uploadStandardPhoto(skuId, fileName, mimeType, bytes, viewType)) {
                is AdminApiResult.Ok -> AdminUploadState.Uploaded(r.value)
                is AdminApiResult.Error -> AdminUploadState.Error(r.message)
            }
    }

    fun addDetectionPoint(
        skuId: String,
        pointCode: String,
        label: String,
        description: String?,
        methodHint: String?,
        expectedValue: String?,
        severity: String,
    ) {
        if (pointCode.isBlank() || label.isBlank()) {
            _pointState.value = AdminPointEditState.Error("point code and label are required")
            return
        }
        // Counting checkpoints must carry an expected count — mirror the
        // backend's fail-closed studio confirm rule (§5.4) at input time.
        if (methodHint == "counting" && expectedValue.isNullOrBlank()) {
            _pointState.value =
                AdminPointEditState.Error("counting checkpoint needs an expected count")
            return
        }
        _pointState.value = AdminPointEditState.Saving
        val r = client.addDetectionPoint(
            skuId, pointCode.trim(), label.trim(), description, methodHint, expectedValue, severity,
        )
        _pointState.value = when (r) {
            is AdminApiResult.Ok -> AdminPointEditState.Saved(r.value)
            is AdminApiResult.Error -> AdminPointEditState.Error(r.message)
        }
    }

    /**
     * Validate drawn regions against the SKU's photo set and persist them.
     * Validation is the backend's exact fail-closed rule set; persistence goes
     * to the pending queue while the WS6 route is backend-pending (state says
     * so explicitly).
     */
    fun saveRegions(detectionPointId: String, regions: List<Region>, validImageIds: Set<String>) {
        val normalized = try {
            RegionValidator.normalize(regions, validImageIds)
        } catch (e: InvalidRegionException) {
            _regionState.value = AdminRegionSaveState.Invalid(e.message ?: "invalid region")
            return
        }
        when (client.saveDetectionPointRegions(detectionPointId, normalized)) {
            is AdminApiResult.Ok -> {
                pendingRegions.clear(detectionPointId)
                _regionState.value = AdminRegionSaveState.SavedToServer(detectionPointId)
            }
            is AdminApiResult.Error -> {
                // TODO(backend-pending: docs/api-contracts/standard-authoring-regions.md)
                // — expected path until WS6 publishes the route.
                pendingRegions.put(detectionPointId, normalized)
                _regionState.value =
                    AdminRegionSaveState.QueuedPendingBackend(detectionPointId, normalized.size)
            }
        }
    }

    fun resetUploadState() { _uploadState.value = AdminUploadState.Idle }
    fun resetPointState() { _pointState.value = AdminPointEditState.Idle }
}
