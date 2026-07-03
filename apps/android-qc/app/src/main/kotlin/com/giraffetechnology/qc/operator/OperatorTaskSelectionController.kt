package com.giraffetechnology.qc.operator

import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.SqliteStandardStore
import com.giraffetechnology.qc.contracts.hasAnyInstalledStandards
import com.giraffetechnology.qc.sku.QcTask
import com.giraffetechnology.qc.sku.SkuResolutionMethod
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Operator task selection over the **offline** on-device standards store (S5 §8.1).
 *
 * Hard requirements enforced here:
 * - Search hits the local [SqliteStandardStore] only — never a LAN backend call.
 * - Empty store → [OperatorTaskState.NoStandardsInstalled] (exact message key
 *   [KEY_NO_STANDARDS]).
 * - Store non-empty but query matches nothing → [OperatorTaskState.SkuNotFound]
 *   (exact message key [KEY_SKU_NOT_FOUND]).
 * - Confirming a SKU hydrates its installed active revision (photos + detection
 *   points) into a [QcTask], carrying the standard revision id for S6 submission.
 *
 * States carry i18n **keys**, not literal strings; the screen resolves them
 * through the language skill so the two exact spec messages stay localizable.
 */
class OperatorTaskSelectionController(
    private val store: SqliteStandardStore,
) {
    private val _state = MutableStateFlow<OperatorTaskState>(OperatorTaskState.Idle)
    val state: StateFlow<OperatorTaskState> = _state.asStateFlow()

    /** Offline search by item number / name. No network. */
    suspend fun search(query: String) {
        if (!store.hasAnyInstalledStandards()) {
            _state.value = OperatorTaskState.NoStandardsInstalled
            return
        }
        val results = store.searchInstalledSku(query.trim())
        _state.value = if (results.isEmpty()) {
            OperatorTaskState.SkuNotFound(query.trim())
        } else {
            OperatorTaskState.Results(results)
        }
    }

    /**
     * Confirm a selected SKU. Requires an explicit operator action (never
     * auto-binds). Builds the [QcTask] from the installed active revision; if the
     * SKU or its revision is missing, falls back to the not-found message.
     */
    suspend fun confirm(skuId: String) {
        val installed = store.getInstalledSku(skuId)
        val revision = store.getInstalledStandardRevision(skuId)
        if (installed == null || revision == null) {
            _state.value = OperatorTaskState.SkuNotFound(skuId)
            return
        }
        val sku = InstalledStandardMapper.toSku(installed, revision)
        _state.value = OperatorTaskState.Confirmed(
            QcTask(
                sku = sku,
                confirmedByUser = true,
                resolvedBy = SkuResolutionMethod.MANUAL_ITEM_NUMBER,
                activeStandardRevisionId = revision.standardRevisionId,
            )
        )
    }

    fun reset() { _state.value = OperatorTaskState.Idle }

    companion object {
        const val KEY_NO_STANDARDS = "pad.task.no_standards_installed"
        const val KEY_SKU_NOT_FOUND = "pad.task.sku_not_found"
    }
}

sealed class OperatorTaskState {
    object Idle : OperatorTaskState()
    data class Results(val skus: List<InstalledSku>) : OperatorTaskState()
    /** No standards are installed at all — resolves [OperatorTaskSelectionController.KEY_NO_STANDARDS]. */
    object NoStandardsInstalled : OperatorTaskState()
    /** Standards are installed but none matched — resolves KEY_SKU_NOT_FOUND. */
    data class SkuNotFound(val query: String) : OperatorTaskState()
    data class Confirmed(val task: QcTask) : OperatorTaskState()
}
