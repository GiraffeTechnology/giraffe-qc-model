package com.giraffetechnology.qc.jetson

import android.util.Base64
import com.giraffetechnology.qc.qwen.CapturePhotoInput
import com.giraffetechnology.qc.qwen.FallbackInfo
import com.giraffetechnology.qc.qwen.InspectionContext
import com.giraffetechnology.qc.qwen.InspectionItemResult
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.QwenInspectionOutput
import com.giraffetechnology.qc.qwen.QwenInspector
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.io.File

/**
 * Real (Jetson LAN) [QwenInspector] implementation -- replaces
 * [com.giraffetechnology.qc.qwen.MnnQwenInspector] as the default inference
 * path (WS4). Calls the paired Jetson's `/infer` over LAN
 * (`docs/api-contracts/jetson-runner-api.md` §1.2/§2) instead of a native
 * on-device JNI call.
 *
 * Known gap, not silently papered over: [QcPointInput] does not currently
 * carry `expected_value`/`pass_criteria`/`severity` (the fields
 * `JetsonDetectionPointSpec` and the real llama.cpp adapter's prompt actually
 * use for judgment) -- those default to empty/`"major"` here rather than
 * being fabricated. Wiring Studio-authored `expected_value`/`pass_criteria`
 * through to `QcPointInput` is a separate, larger change (touches wherever
 * `QcTask`/`QcPointInput` are constructed from bundle data) and is out of
 * WS4's scope; flagged for a follow-up rather than guessed at here. Region
 * annotation data (WS6) is likewise not wired into the per-point request yet
 * -- every point's `regions` is sent empty.
 */
class JetsonQwenInspector(
    private val pairingStore: JetsonPairingRepository,
    private val client: JetsonLanClient = JetsonLanClient(),
    override val modelName: String = "jetson-lan",
    private val timeoutMs: Long = 30_000L,
) : QwenInspector {

    override val engineName: String = "jetson_lan"

    override suspend fun inspect(
        standardPhotos: List<StandardPhotoInput>,
        capturedPhoto: CapturePhotoInput,
        qcPoints: List<QcPointInput>,
        context: InspectionContext,
    ): QwenInspectionOutput {
        val baseUrl = pairingStore.jetsonHost?.let { "http://$it:${pairingStore.jetsonPort}" }
            ?: throw IllegalStateException("jetson_not_paired")
        val pairKey = pairingStore.pairKey ?: throw IllegalStateException("jetson_not_paired")

        val imageDataUri = withContext(Dispatchers.IO) { encodeImageAsDataUri(capturedPhoto.localPath) }

        val request = JetsonInferenceRequest(
            jobId = context.inspectionId,
            standardRevisionId = context.standardId,
            bundleVersion = "",
            image = imageDataUri,
            detectionPoints = qcPoints.map { p ->
                JetsonDetectionPointSpec(pointCode = p.qcPointCode, label = p.name, description = p.description)
            },
        )

        val outcome = try {
            withTimeout(timeoutMs) {
                withContext(Dispatchers.IO) { client.infer(baseUrl, pairingStore.padDeviceId, pairKey, request) }
            }
        } catch (e: TimeoutCancellationException) {
            throw IllegalStateException("jetson_infer_timeout")
        }

        val response = when (outcome) {
            is JetsonLanClient.InferOutcome.Success -> outcome.response
            is JetsonLanClient.InferOutcome.Unreachable -> throw IllegalStateException("jetson_unreachable")
            is JetsonLanClient.InferOutcome.Rejected -> throw IllegalStateException("jetson_rejected:${outcome.reason}")
        }

        val byPointCode = qcPoints.associateBy { it.qcPointCode }
        val items = response.perPointResults.map { r ->
            val point = byPointCode[r.pointCode]
            InspectionItemResult(
                qcPointId = point?.qcPointId ?: r.pointCode,
                qcPointCode = r.pointCode,
                name = point?.name ?: r.pointCode,
                // Jetson's per-point vocabulary is pass|fail|uncertain (§4);
                // the Pad's InspectionItemResult vocabulary is
                // pass|fail|review_required -- "uncertain" is never silently
                // treated as pass or fail.
                result = when (r.result) {
                    "pass" -> "pass"
                    "fail" -> "fail"
                    else -> "review_required"
                },
                confidence = r.confidence,
                reason = r.evidence,
            )
        }

        // Never trust the model's self-reported overall verdict (same
        // no-guess-rules principle as QcResultParser): recompute
        // deterministically from the per-point results.
        val overall = when {
            items.any { it.result == "fail" } -> "fail"
            items.any { it.result == "review_required" } -> "review_required"
            items.isNotEmpty() && items.all { it.result == "pass" } -> "pass"
            else -> "review_required"
        }

        return QwenInspectionOutput(
            overallResult = overall,
            engine = engineName,
            modelName = modelName,
            confidence = items.map { it.confidence }.average().takeIf { !it.isNaN() }?.toFloat() ?: 0f,
            items = items,
            fallback = FallbackInfo(used = false),
            summary = "jetson_lan inference for ${items.size} detection point(s)",
        )
    }

    private fun encodeImageAsDataUri(localPath: String): String {
        val file = File(localPath)
        val bytes = file.readBytes()
        val mime = when (file.extension.lowercase()) {
            "png" -> "image/png"
            "webp" -> "image/webp"
            else -> "image/jpeg"
        }
        val b64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
        return "data:$mime;base64,$b64"
    }
}
