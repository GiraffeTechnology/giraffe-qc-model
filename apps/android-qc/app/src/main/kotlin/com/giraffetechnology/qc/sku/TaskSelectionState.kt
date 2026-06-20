package com.giraffetechnology.qc.sku

sealed class TaskSelectionState {
    data object Idle                                                  : TaskSelectionState()
    data object ManualSearching                                       : TaskSelectionState()
    data class  ManualResults(val results: List<Sku>)                 : TaskSelectionState()
    data object CapturingForMatch                                     : TaskSelectionState()
    data object Matching                                              : TaskSelectionState()
    data class  MatchCandidates(val result: SkuMatchResult)           : TaskSelectionState()
    data object MnnPending                                            : TaskSelectionState()
    data class  TaskConfirmed(val task: QcTask)                       : TaskSelectionState()
    data class  Error(val reason: String)                             : TaskSelectionState()
}
