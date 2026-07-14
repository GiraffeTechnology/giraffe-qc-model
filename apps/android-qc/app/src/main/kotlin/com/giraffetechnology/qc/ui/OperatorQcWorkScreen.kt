package com.giraffetechnology.qc.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.giraffetechnology.qc.camera.CameraXCaptureController
import com.giraffetechnology.qc.capture.AutoCaptureController
import com.giraffetechnology.qc.capture.AutoCaptureState
import com.giraffetechnology.qc.i18n.LanguageController
import com.giraffetechnology.qc.operator.cloud.CloudRuntimeMonitor
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader
import com.giraffetechnology.qc.readiness.JetsonPadReadiness
import com.giraffetechnology.qc.readiness.CloudPadReadiness
import com.giraffetechnology.qc.readiness.PadReadiness
import com.giraffetechnology.qc.sku.MnnRuntime
import com.giraffetechnology.qc.sku.PadInspectionCoordinator
import com.giraffetechnology.qc.sku.PadInspectionResult
import com.giraffetechnology.qc.sku.QcTask
import com.giraffetechnology.qc.work.ConversationBuilder
import com.giraffetechnology.qc.work.ConversationEntry
import kotlinx.coroutines.launch

/**
 * QC Work page (S6 §8.2) — landscape split layout:
 * - Left: dominant 4:3 live camera view.
 * - Right-top: 4:3 standard/reference image for the selected SKU.
 * - Right-middle: scrollable conversation/inspection log (§3.4 bubbles).
 * - Right-bottom: input box with a text/voice switch.
 *
 * The conversation surfaces the §8.2 content set (SKU, standard revision/bundle,
 * readiness, instructions, checkpoints, results) via [ConversationBuilder], and
 * the runtime-readiness lines are the exact §8.3 states, never overclaiming
 * (fail-closed per PR30 through [PadReadiness]).
 */
@Composable
fun OperatorQcWorkScreen(
    task: QcTask,
    languageController: LanguageController,
    autoCaptureController: AutoCaptureController,
    runtimeLoader: MnnRuntime,
    cameraXController: CameraXCaptureController,
    inspectionCoordinator: PadInspectionCoordinator?,
    onInspectionResult: (PadInspectionResult) -> Unit,
    onBack: () -> Unit,
    online: Boolean = false,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val runtimeState by runtimeLoader.runtimeState.collectAsState()
    val captureState by autoCaptureController.state.collectAsState()
    val isCameraReady by cameraXController.isReady.collectAsState()
    val context = LocalContext.current

    val conversation = remember { mutableStateListOf<ConversationEntry>() }
    var inputText by remember { mutableStateOf("") }
    var voiceMode by remember { mutableStateOf(false) }

    // Which readiness wording set applies depends on which concrete runtime
    // PadRuntimeGraph wired in -- the coordinator/gating logic itself is
    // identical either way (both satisfy MnnRuntime).
    val standardInstalled = task.standardPhotos.isNotEmpty() && task.qcPoints.isNotEmpty()
    val readiness = if (runtimeLoader is CloudRuntimeMonitor) {
        CloudPadReadiness.fromRuntimeState(runtimeState, standardInstalled, true)
    } else if (runtimeLoader is MnnRuntimeLoader) {
        PadReadiness.fromRuntimeState(
            state = runtimeState,
            inferenceVerified = runtimeLoader.inferenceVerified,
            standardInstalled = standardInstalled,
            skuSelected = true,
            online = online,
        )
    } else {
        JetsonPadReadiness.fromRuntimeState(
            state = runtimeState,
            inferenceVerified = runtimeLoader.inferenceVerified,
            standardInstalled = standardInstalled,
            skuSelected = true,
            online = online,
        )
    }
    val cloudRuntime = runtimeLoader as? CloudRuntimeMonitor

    // Seed the log once when the page opens.
    LaunchedEffect(task.sku.id) {
        conversation.clear()
        conversation.addAll(ConversationBuilder.sessionOpening(task, readiness, skill))
    }

    var cameraPermState by remember {
        val granted = ContextCompat.checkSelfPermission(
            context, Manifest.permission.CAMERA,
        ) == PackageManager.PERMISSION_GRANTED
        mutableStateOf(if (granted) CameraPermissionState.Granted else CameraPermissionState.Checking)
    }
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> cameraPermState = resolvePermissionState(granted) }

    fun runInspection(onDone: (PadInspectionResult) -> Unit) {
        scope.launch {
            val photo = runCatching { cameraXController.captureStill() }.getOrNull()
            val result = if (photo != null && inspectionCoordinator != null) {
                inspectionCoordinator.inspect(task, photo)
            } else {
                PadInspectionResult(
                    overallResult = "CLOUD_UNAVAILABLE",
                    reason = skill.t("pad.work.cloud_unavailable_no_verdict"),
                    modelName = runtimeLoader.javaClass.simpleName,
                    localOnly = false,
                    cloudInferenceUsed = true,
                    capturedImagePath = photo?.rawImagePath,
                )
            }
            conversation.add(ConversationBuilder.resultSummary(result, skill))
            onDone(result)
        }
    }

    // Auto-capture path also drives inspection.
    LaunchedEffect(captureState) {
        if (captureState is AutoCaptureState.Captured) {
            val photo = (captureState as AutoCaptureState.Captured).capture
            val result = inspectionCoordinator?.inspect(task, photo)
                ?: PadInspectionResult(
                    overallResult = "CLOUD_UNAVAILABLE",
                    reason = skill.t("pad.work.coordinator_unavailable_no_verdict"),
                    modelName = runtimeLoader.javaClass.simpleName,
                    localOnly = false,
                    cloudInferenceUsed = true,
                    capturedImagePath = photo.rawImagePath,
                )
            conversation.add(ConversationBuilder.resultSummary(result, skill))
            onInspectionResult(result)
        }
    }

    Row(modifier = Modifier.fillMaxSize()) {
        // ── Left: dominant 4:3 live camera ────────────────────────────────
        Box(
            modifier = Modifier.weight(3f).fillMaxHeight().background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            when (cameraPermState) {
                CameraPermissionState.Granted -> BoxWithConstraints(contentAlignment = Alignment.Center) {
                    val (w, h) = fitAspect43(maxWidth.value, maxHeight.value)
                    Box(
                        modifier = Modifier.size(width = w.dp, height = h.dp).border(2.dp, Color.DarkGray),
                    ) {
                        CameraPreviewPane(controller = cameraXController, modifier = Modifier.fillMaxSize())
                    }
                }
                CameraPermissionState.Checking -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        skill.t("pad.work.camera_permission_required"),
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = { permLauncher.launch(Manifest.permission.CAMERA) }) {
                        Text(skill.t("pad.work.capture"))
                    }
                }
                CameraPermissionState.Denied -> Text(
                    skill.t("pad.work.camera_permission_denied"),
                    color = Color(0xFFEF5350),
                    fontWeight = FontWeight.Bold,
                )
            }
        }

        // ── Right: reference (4:3) · log · input ──────────────────────────
        Column(
            modifier = Modifier.weight(2f).fillMaxHeight()
                .background(MaterialTheme.colorScheme.surface).padding(8.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(skill.t("pad.work.title"), fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                LanguageSwitch(languageController)
            }

            // Architecture v2: Operator readiness is cloud/link state. Xavier
            // MNN is Administrator-only and never appears as this runtime.
            cloudRuntime?.let { monitor ->
                Text(
                    "${if (monitor.cloudReachable) "●" else "○"} Cloud · ${monitor.lastDecision.selected.wire}" +
                        if (monitor.lastDecision.breaches.isEmpty()) "" else " · ${monitor.lastDecision.breaches.joinToString()}",
                    fontSize = 10.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // Right-top: 4:3 reference image.
            Text(
                skill.t("pad.work.reference"),
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ReferenceImagePane(
                localPhotoPath = task.standardPhotos.firstOrNull()?.localPath
                    ?: task.sku.standardPhotoPath,
                placeholderLabel = task.sku.referenceImageUrl ?: skill.t("pad.work.reference"),
                modifier = Modifier.fillMaxWidth().aspectRatio(4f / 3f),
            )
            Spacer(Modifier.height(6.dp))

            // Right-middle: scrollable conversation/inspection log.
            ConversationLog(entries = conversation, modifier = Modifier.weight(1f).fillMaxWidth())
            Spacer(Modifier.height(6.dp))

            // Right-bottom: input box with text/voice switch.
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { voiceMode = false }) {
                    Text(
                        skill.t("pad.work.text"),
                        fontWeight = if (!voiceMode) FontWeight.Bold else FontWeight.Normal,
                    )
                }
                TextButton(onClick = { voiceMode = true }) {
                    Text(
                        skill.t("pad.work.voice"),
                        fontWeight = if (voiceMode) FontWeight.Bold else FontWeight.Normal,
                    )
                }
            }
            if (voiceMode) {
                // Controlled fallback: voice STT is not wired on device yet.
                Text(
                    skill.t("common.error_generic"),
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = inputText,
                    onValueChange = { inputText = it },
                    label = { Text(skill.t("pad.work.input_hint")) },
                    singleLine = true,
                    enabled = !voiceMode,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(4.dp))
                Button(
                    onClick = {
                        if (inputText.isNotBlank()) {
                            conversation.add(ConversationBuilder.operatorMessage(inputText.trim()))
                            inputText = ""
                        }
                    },
                    enabled = !voiceMode && inputText.isNotBlank(),
                ) { Text(skill.t("pad.work.send")) }
            }
            Spacer(Modifier.height(6.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onBack) { Text(skill.t("common.cancel")) }
                Spacer(Modifier.weight(1f))
                Button(
                    onClick = { runInspection { result -> onInspectionResult(result) } },
                    enabled = isCameraReady && cameraPermState == CameraPermissionState.Granted,
                ) { Text(skill.t("pad.work.capture")) }
            }
        }
    }
}
