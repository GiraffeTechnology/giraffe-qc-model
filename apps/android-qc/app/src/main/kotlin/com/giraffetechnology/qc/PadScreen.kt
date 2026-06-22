package com.giraffetechnology.qc

import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask

sealed class PadScreen {
    object TaskSelection : PadScreen()
    data class QcCapture(val task: QcTask) : PadScreen()
    data class Result(val task: QcTask, val result: PadInspectionResult) : PadScreen()
}
