package com.giraffetechnology.qc.multimodal

/**
 * Shared contract constants for the provider-neutral QC result schema.
 *
 * Both server (Python src/multimodal/contract.py) and Pad embed QC_CONTRACT_VERSION
 * in every inspection result. A mismatch must be logged — never silently accepted.
 *
 * Result values are locked to the three canonical strings below.
 * Any other string from a provider must be normalised to RESULT_REVIEW_REQUIRED (fail-closed).
 */
object SharedQcContract {

    const val QC_CONTRACT_VERSION = "multimodal-qc-v1"

    const val RESULT_PASS = "pass"
    const val RESULT_FAIL = "fail"
    const val RESULT_REVIEW_REQUIRED = "review_required"

    val VALID_RESULTS: Set<String> = setOf(RESULT_PASS, RESULT_FAIL, RESULT_REVIEW_REQUIRED)

    fun isValidResult(value: String): Boolean = value in VALID_RESULTS

    /**
     * Normalise an unknown or null result value to review_required (fail-closed).
     * Never normalise to pass.
     */
    fun normalizeResult(value: String?): String =
        if (value != null && value in VALID_RESULTS) value else RESULT_REVIEW_REQUIRED
}
