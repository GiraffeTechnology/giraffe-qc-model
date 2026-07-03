package com.giraffetechnology.qc

import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask

sealed class PadScreen {
    /** Entry screen (S5 §3.1): Giraffe icon, Administrator / Operator branches. */
    object Welcome : PadScreen()
    /** Administrator branch lands here — admin management runs on the Web console. */
    object AdministratorInfo : PadScreen()
    /** Operator branch (S5 §8.1): offline search of standards installed on this Pad. */
    object OperatorTaskSelection : PadScreen()
    /** QC Work page (S6 §8.2): split camera / reference / conversation / input. */
    data class QcWork(val task: QcTask) : PadScreen()
    /** Result review + human decision → outbox (S6 §9). */
    data class ResultReview(val task: QcTask, val result: PadInspectionResult) : PadScreen()
    /** Outbox / sync status (S6). */
    object SyncStatus : PadScreen()

    /** Legacy backend-LAN SKU search flow (kept for the online task path). */
    object TaskSelection : PadScreen()
    data class QcCapture(val task: QcTask) : PadScreen()
    data class Result(val task: QcTask, val result: PadInspectionResult) : PadScreen()
}
