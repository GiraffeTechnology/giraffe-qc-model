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

sealed class AdminProcessCardUploadState {
    object Idle : AdminProcessCardUploadState()
    object Uploading : AdminProcessCardUploadState()
    data class Uploaded(val trainingPackId: String) : AdminProcessCardUploadState()
    data class Error(val message: String) : AdminProcessCardUploadState()
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
    data class QueuedForRetry(
        val detectionPointId: String,
        val count: Int,
        val message: String,
    ) : AdminRegionSaveState()
    data class SavedToServer(val detectionPointId: String) : AdminRegionSaveState()
}

sealed class AdminCategoryState {
    object Idle : AdminCategoryState()
    object Loading : AdminCategoryState()
    object Confirming : AdminCategoryState()
    data class Loaded(
        val options: List<AdminCheckpointCategory>,
        val byPointId: Map<String, AdminDetectionPointCategory>,
    ) : AdminCategoryState()
    data class Error(val message: String) : AdminCategoryState()
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

    private val _processCardUploadState =
        MutableStateFlow<AdminProcessCardUploadState>(AdminProcessCardUploadState.Idle)
    val processCardUploadState: StateFlow<AdminProcessCardUploadState> =
        _processCardUploadState.asStateFlow()

    private val _pointState = MutableStateFlow<AdminPointEditState>(AdminPointEditState.Idle)
    val pointState: StateFlow<AdminPointEditState> = _pointState.asStateFlow()

    private val _regionState = MutableStateFlow<AdminRegionSaveState>(AdminRegionSaveState.Idle)
    val regionState: StateFlow<AdminRegionSaveState> = _regionState.asStateFlow()

    private val _categoryState = MutableStateFlow<AdminCategoryState>(AdminCategoryState.Idle)
    val categoryState: StateFlow<AdminCategoryState> = _categoryState.asStateFlow()

    val pendingRegionsByPoint: StateFlow<Map<String, List<Region>>> = pendingRegions.pending

    fun uploadPhoto(
        skuId: String,
        fileName: String,
        mimeType: String,
        bytes: ByteArray,
        viewType: String?,
    ) {
        if (bytes.isEmpty()) {
            _uploadState.value = AdminUploadState.Error("admin.error.empty_file")
            return
        }
        _uploadState.value = AdminUploadState.Uploading
        _uploadState.value =
            when (val r = client.uploadStandardPhoto(skuId, fileName, mimeType, bytes, viewType)) {
                is AdminApiResult.Ok -> AdminUploadState.Uploaded(r.value)
                is AdminApiResult.Error -> AdminUploadState.Error(r.message)
            }
    }

    fun uploadProcessCard(
        trainingPackId: String,
        fileName: String,
        mimeType: String,
        bytes: ByteArray,
    ) {
        if (trainingPackId.isBlank()) {
            _processCardUploadState.value =
                AdminProcessCardUploadState.Error("admin.error.training_pack_required")
            return
        }
        if (bytes.isEmpty()) {
            _processCardUploadState.value = AdminProcessCardUploadState.Error("admin.error.empty_file")
            return
        }
        _processCardUploadState.value = AdminProcessCardUploadState.Uploading
        _processCardUploadState.value = when (
            val r = client.uploadProcessCard(
                trainingPackId.trim(), fileName, mimeType, bytes,
            )
        ) {
            is AdminApiResult.Ok -> AdminProcessCardUploadState.Uploaded(trainingPackId.trim())
            is AdminApiResult.Error -> AdminProcessCardUploadState.Error(r.message)
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
            _pointState.value = AdminPointEditState.Error("admin.error.point_code_label_required")
            return
        }
        // Counting checkpoints must carry an expected count — mirror the
        // backend's fail-closed studio confirm rule (§5.4) at input time.
        if (methodHint == "counting" && expectedValue.isNullOrBlank()) {
            _pointState.value =
                AdminPointEditState.Error("admin.error.counting_expected_required")
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

    fun updateDetectionPoint(
        detectionPointId: String,
        pointCode: String,
        label: String,
        description: String?,
        methodHint: String?,
        expectedValue: String?,
        severity: String,
    ) {
        val validationError = validatePoint(pointCode, label, methodHint, expectedValue)
        if (validationError != null) {
            _pointState.value = AdminPointEditState.Error(validationError)
            return
        }
        _pointState.value = AdminPointEditState.Saving
        val r = client.updateDetectionPoint(
            detectionPointId, pointCode.trim(), label.trim(), description,
            methodHint, expectedValue, severity,
        )
        _pointState.value = when (r) {
            is AdminApiResult.Ok -> AdminPointEditState.Saved(r.value)
            is AdminApiResult.Error -> AdminPointEditState.Error(r.message)
        }
    }

    fun loadCategories(skuId: String) {
        _categoryState.value = AdminCategoryState.Loading
        val options = when (val r = client.fetchCheckpointCategories()) {
            is AdminApiResult.Ok -> r.value
            is AdminApiResult.Error -> {
                _categoryState.value = AdminCategoryState.Error(r.message)
                return
            }
        }
        _categoryState.value = when (val r = client.fetchDetectionPointCategories(skuId)) {
            is AdminApiResult.Ok -> AdminCategoryState.Loaded(
                options = options,
                byPointId = r.value.associateBy { it.detectionPointId },
            )
            is AdminApiResult.Error -> AdminCategoryState.Error(r.message)
        }
    }

    fun confirmCategory(skuId: String, detectionPointId: String, category: String) {
        _categoryState.value = AdminCategoryState.Confirming
        when (val r = client.confirmDetectionPointCategory(detectionPointId, category)) {
            is AdminApiResult.Ok -> loadCategories(skuId)
            is AdminApiResult.Error -> _categoryState.value = AdminCategoryState.Error(r.message)
        }
    }

    /**
     * Validate drawn regions against the SKU's photo set and persist them.
     * A transient server/network failure is retained for an explicit retry and
     * never presented as a successful save.
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
                pendingRegions.put(detectionPointId, normalized)
                _regionState.value =
                    AdminRegionSaveState.QueuedForRetry(
                        detectionPointId, normalized.size, "admin.error.region_save_retry",
                    )
            }
        }
    }

    private fun validatePoint(
        pointCode: String,
        label: String,
        methodHint: String?,
        expectedValue: String?,
    ): String? = when {
        pointCode.isBlank() || label.isBlank() -> "admin.error.point_code_label_required"
        methodHint == "counting" && expectedValue.isNullOrBlank() ->
            "admin.error.counting_expected_required"
        else -> null
    }

    fun resetUploadState() { _uploadState.value = AdminUploadState.Idle }
    fun resetProcessCardUploadState() {
        _processCardUploadState.value = AdminProcessCardUploadState.Idle
    }
    fun resetPointState() { _pointState.value = AdminPointEditState.Idle }
}
