package com.giraffetechnology.qc.ui.admin

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.gestures.detectDragGestures
import com.giraffetechnology.qc.admin.AdminApiClient
import com.giraffetechnology.qc.admin.AdminCategoryState
import com.giraffetechnology.qc.admin.AdminDetectionPoint
import com.giraffetechnology.qc.admin.AdminPointEditState
import com.giraffetechnology.qc.admin.AdminProcessCardUploadState
import com.giraffetechnology.qc.admin.AdminRegionSaveState
import com.giraffetechnology.qc.admin.AdminSkuController
import com.giraffetechnology.qc.admin.AdminStandardController
import com.giraffetechnology.qc.admin.AdminUploadState
import com.giraffetechnology.qc.admin.Region
import com.giraffetechnology.qc.i18n.LanguageController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

private enum class AdminDocumentUploadTarget { STANDARD_PHOTO, PROCESS_CARD }

/**
 * Standard authoring for one SKU (WS3 items 3–5):
 *  - reference photo / process-card upload (file picker → multipart upload),
 *  - detection point add/edit + category (method/severity) input,
 *  - region drawing on a standard photo, using the backend's exact
 *    `{image_id, x, y, w, h}` normalized bounding-box model.
 */
@Composable
fun AdminStandardScreen(
    skuId: String,
    skuController: AdminSkuController,
    standardController: AdminStandardController,
    client: AdminApiClient,
    languageController: LanguageController,
    onPublish: (String) -> Unit,
    onBack: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val skill by languageController.skill.collectAsState()
    val sku by skuController.selected.collectAsState()
    val uploadState by standardController.uploadState.collectAsState()
    val processCardUploadState by standardController.processCardUploadState.collectAsState()
    val pointState by standardController.pointState.collectAsState()
    val regionState by standardController.regionState.collectAsState()
    val categoryState by standardController.categoryState.collectAsState()
    val pendingRegions by standardController.pendingRegionsByPoint.collectAsState()

    val context = androidx.compose.ui.platform.LocalContext.current
    var uploadTarget by remember {
        mutableStateOf(AdminDocumentUploadTarget.STANDARD_PHOTO)
    }
    var trainingPackId by remember { mutableStateOf("") }

    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            scope.launch(Dispatchers.IO) {
                val resolver = context.contentResolver
                val bytes = resolver.openInputStream(uri)?.use { it.readBytes() } ?: ByteArray(0)
                val mime = resolver.getType(uri) ?: "application/octet-stream"
                val name = uri.lastPathSegment ?: "upload"
                when (uploadTarget) {
                    AdminDocumentUploadTarget.STANDARD_PHOTO -> {
                        standardController.uploadPhoto(skuId, name, mime, bytes, null)
                        skuController.reloadSelected()
                    }
                    AdminDocumentUploadTarget.PROCESS_CARD -> {
                        standardController.uploadProcessCard(
                            trainingPackId, name, mime, bytes,
                        )
                    }
                }
            }
        }
    }

    LaunchedEffect(skuId) {
        scope.launch(Dispatchers.IO) {
            skuController.select(skuId)
            standardController.loadCategories(skuId)
        }
    }
    // Refresh the SKU card after successful uploads / point saves.
    LaunchedEffect(uploadState, pointState) {
        if (uploadState is AdminUploadState.Uploaded || pointState is AdminPointEditState.Saved) {
            scope.launch(Dispatchers.IO) {
                skuController.reloadSelected()
                if (pointState is AdminPointEditState.Saved) {
                    standardController.loadCategories(skuId)
                }
            }
        }
    }

    var selectedPhotoId by remember { mutableStateOf<String?>(null) }
    var selectedPointId by remember { mutableStateOf<String?>(null) }
    var draftRegions by remember { mutableStateOf<List<Region>>(emptyList()) }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        AdminScreenHeader(
            title = skill.t("admin.standard.title"),
            languageController = languageController,
            backLabel = skill.t("admin.back"),
            onBack = onBack,
        )
        val s = sku
        if (s == null) {
            Spacer(Modifier.height(12.dp))
            Text(skill.t("common.loading"), fontSize = 13.sp)
            return@Column
        }
        Text("${s.itemNumber} — ${s.name}", fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))

        Row(modifier = Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(16.dp)) {

            // ── Left: photos + upload + region canvas ────────────────────────
            Column(modifier = Modifier.weight(1.2f).verticalScroll(rememberScrollState())) {
                Text(skill.t("admin.standard.photos"), fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        uploadTarget = AdminDocumentUploadTarget.STANDARD_PHOTO
                        filePicker.launch("image/*")
                    }) {
                        Text(skill.t("admin.standard.upload_photo"))
                    }
                    OutlinedButton(
                        enabled = trainingPackId.isNotBlank(),
                        onClick = {
                            uploadTarget = AdminDocumentUploadTarget.PROCESS_CARD
                            filePicker.launch("*/*")
                        },
                    ) {
                        Text(skill.t("admin.standard.upload_process_card"))
                    }
                }
                OutlinedTextField(
                    value = trainingPackId,
                    onValueChange = {
                        trainingPackId = it
                        standardController.resetProcessCardUploadState()
                    },
                    label = { Text(skill.t("admin.standard.training_pack_id")) },
                    supportingText = {
                        Text(skill.t("admin.standard.process_card_supported_formats"))
                    },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                when (val u = uploadState) {
                    is AdminUploadState.Uploading -> Text(skill.t("admin.standard.uploading"), fontSize = 12.sp)
                    is AdminUploadState.Uploaded ->
                        AdminOkBanner(skill.t("admin.standard.photo_uploaded"))
                    is AdminUploadState.Error -> AdminErrorBanner(skill.t(u.message))
                    else -> {}
                }
                when (val u = processCardUploadState) {
                    is AdminProcessCardUploadState.Uploading ->
                        Text(skill.t("admin.standard.process_card_uploading"), fontSize = 12.sp)
                    is AdminProcessCardUploadState.Uploaded ->
                        AdminOkBanner(skill.t("admin.standard.process_card_uploaded"))
                    is AdminProcessCardUploadState.Error -> AdminErrorBanner(skill.t(u.message))
                    else -> {}
                }
                Spacer(Modifier.height(8.dp))

                LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(s.photos) { photo ->
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            modifier = Modifier
                                .clickable { selectedPhotoId = photo.id }
                                .border(
                                    width = if (selectedPhotoId == photo.id) 2.dp else 1.dp,
                                    color = if (selectedPhotoId == photo.id)
                                        MaterialTheme.colorScheme.primary else Color.LightGray,
                                )
                                .padding(4.dp),
                        ) {
                            RemoteImage(
                                url = if (photo.url.startsWith("http")) photo.url
                                else com.giraffetechnology.qc.BuildConfig.SKU_API_BASE_URL + photo.url,
                                cookie = client.identity?.sessionCookie,
                                modifier = Modifier.size(96.dp),
                            )
                            Text(photo.viewType ?: skill.t("admin.standard.photo_default"), fontSize = 10.sp)
                        }
                    }
                }
                Spacer(Modifier.height(12.dp))

                // Region editor on the selected photo.
                val photo = s.photos.firstOrNull { it.id == selectedPhotoId }
                if (photo != null) {
                    Text(skill.t("admin.standard.regions"), fontWeight = FontWeight.SemiBold)
                    Text(skill.t("admin.standard.regions.hint"), fontSize = 11.sp)
                    Spacer(Modifier.height(4.dp))
                    RegionEditorCanvas(
                        imageUrl = if (photo.url.startsWith("http")) photo.url
                        else com.giraffetechnology.qc.BuildConfig.SKU_API_BASE_URL + photo.url,
                        imageId = photo.id,
                        cookie = client.identity?.sessionCookie,
                        existing = draftRegions.filter { it.imageId == photo.id },
                        onRegionDrawn = { region -> draftRegions = draftRegions + region },
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = { draftRegions = emptyList() }) {
                            Text(skill.t("admin.standard.regions.clear"))
                        }
                        Button(
                            enabled = selectedPointId != null,
                            onClick = {
                                val pointId = selectedPointId ?: return@Button
                                scope.launch(Dispatchers.IO) {
                                    standardController.saveRegions(
                                        pointId, draftRegions,
                                        s.photos.map { it.id }.toSet(),
                                    )
                                }
                            },
                        ) { Text(skill.t("admin.standard.regions.save")) }
                    }
                    when (val r = regionState) {
                        is AdminRegionSaveState.Invalid -> AdminErrorBanner(skill.t(r.message))
                        is AdminRegionSaveState.QueuedForRetry -> AdminErrorBanner(
                            skill.t("admin.standard.regions.pending") +
                                " (${r.count}): ${skill.t(r.message)}"
                        )
                        is AdminRegionSaveState.SavedToServer ->
                            AdminOkBanner(skill.t("admin.standard.regions.saved"))
                        else -> {}
                    }
                }
            }

            // ── Right: detection points list + add form ──────────────────────
            Column(modifier = Modifier.weight(1f)) {
                Text(skill.t("admin.standard.points"), fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(4.dp))
                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(s.detectionPoints) { dp ->
                        val isSel = selectedPointId == dp.id
                        val pendingCount = pendingRegions[dp.id]?.size ?: 0
                        Surface(
                            tonalElevation = 1.dp,
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    selectedPointId = dp.id
                                    draftRegions = dp.regions
                                }
                                .border(
                                    width = if (isSel) 2.dp else 0.dp,
                                    color = if (isSel) MaterialTheme.colorScheme.primary
                                    else Color.Transparent,
                                ),
                        ) {
                            Column(modifier = Modifier.padding(8.dp)) {
                                Text("${dp.pointCode} — ${dp.label}", fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold)
                                Text(
                                    listOfNotNull(
                                        dp.methodHint, dp.severity,
                                        dp.expectedValue?.let { "= $it" },
                                    ).joinToString(" · "),
                                    fontSize = 11.sp,
                                )
                                if (dp.regions.isNotEmpty() || pendingCount > 0) {
                                    Text(
                                        skill.t("admin.standard.point.regions") +
                                            ": ${dp.regions.size}" +
                                            if (pendingCount > 0) " (+$pendingCount ${skill.t("admin.standard.point.pending")})" else "",
                                        fontSize = 11.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                val classification =
                                    (categoryState as? AdminCategoryState.Loaded)?.byPointId?.get(dp.id)
                                if (classification != null) {
                                    val category = classification.confirmedCategory
                                        ?: "proposed: ${classification.proposedCategory}"
                                    Text(
                                        "$category · ${classification.aiRole}",
                                        fontSize = 11.sp,
                                        color = if (classification.confirmedCategory != null)
                                            Color(0xFF2E7D32) else MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))

                DetectionPointForm(
                    skill = skill,
                    pointState = pointState,
                    selectedPoint = s.detectionPoints.firstOrNull { it.id == selectedPointId },
                    onAdd = { code, label, method, expected, severity ->
                        scope.launch(Dispatchers.IO) {
                            standardController.addDetectionPoint(
                                skuId, code, label, null, method, expected, severity,
                            )
                        }
                    },
                    onUpdate = { pointId, code, label, method, expected, severity ->
                        scope.launch(Dispatchers.IO) {
                            standardController.updateDetectionPoint(
                                pointId, code, label, null, method, expected, severity,
                            )
                        }
                    },
                )
                CategoryConfirmationPanel(
                    skill = skill,
                    state = categoryState,
                    selectedPointId = selectedPointId,
                    onConfirm = { pointId, category ->
                        scope.launch(Dispatchers.IO) {
                            standardController.confirmCategory(skuId, pointId, category)
                        }
                    },
                )
                Spacer(Modifier.height(8.dp))
                Button(onClick = { onPublish(skuId) }, modifier = Modifier.fillMaxWidth()) {
                    Text(skill.t("admin.standard.to_publish"))
                }
            }
        }
    }
}

@Composable
private fun DetectionPointForm(
    skill: com.giraffetechnology.qc.contracts.GiraffeLanguageSkill,
    pointState: AdminPointEditState,
    selectedPoint: AdminDetectionPoint?,
    onAdd: (code: String, label: String, method: String?, expected: String?, severity: String) -> Unit,
    onUpdate: (
        pointId: String,
        code: String,
        label: String,
        method: String?,
        expected: String?,
        severity: String,
    ) -> Unit,
) {
    var code by remember { mutableStateOf("") }
    var label by remember { mutableStateOf("") }
    var method by remember { mutableStateOf("presence") }
    var expected by remember { mutableStateOf("") }
    var severity by remember { mutableStateOf("major") }
    var methodMenu by remember { mutableStateOf(false) }
    var severityMenu by remember { mutableStateOf(false) }

    LaunchedEffect(selectedPoint?.id) {
        selectedPoint?.let { point ->
            code = point.pointCode
            label = point.label
            method = point.methodHint ?: "presence"
            expected = point.expectedValue.orEmpty()
            severity = point.severity
        }
    }

    Column {
        Text(skill.t("admin.standard.add_point"), fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(
                value = code, onValueChange = { code = it },
                label = { Text(skill.t("admin.standard.point.code")) },
                singleLine = true, modifier = Modifier.width(120.dp),
            )
            OutlinedTextField(
                value = label, onValueChange = { label = it },
                label = { Text(skill.t("admin.standard.point.label")) },
                singleLine = true, modifier = Modifier.weight(1f),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column {
                OutlinedButton(onClick = { methodMenu = true }) {
                    Text(skill.t("admin.standard.method.$method"))
                }
                DropdownMenu(expanded = methodMenu, onDismissRequest = { methodMenu = false }) {
                    listOf("presence", "counting", "measurement", "text", "color").forEach { m ->
                        DropdownMenuItem(
                            text = { Text(skill.t("admin.standard.method.$m")) },
                            onClick = { method = m; methodMenu = false },
                        )
                    }
                }
            }
            Column {
                OutlinedButton(onClick = { severityMenu = true }) {
                    Text(skill.t("admin.standard.severity.$severity"))
                }
                DropdownMenu(expanded = severityMenu, onDismissRequest = { severityMenu = false }) {
                    listOf("minor", "major", "critical").forEach { sev ->
                        DropdownMenuItem(
                            text = { Text(skill.t("admin.standard.severity.$sev")) },
                            onClick = { severity = sev; severityMenu = false },
                        )
                    }
                }
            }
            OutlinedTextField(
                value = expected, onValueChange = { expected = it },
                label = { Text(skill.t("admin.standard.point.expected")) },
                singleLine = true, modifier = Modifier.width(140.dp),
            )
        }
        when (pointState) {
            is AdminPointEditState.Error -> AdminErrorBanner(skill.t(pointState.message))
            is AdminPointEditState.Saved -> AdminOkBanner(skill.t("admin.standard.point.saved"))
            is AdminPointEditState.Saving -> Text(skill.t("common.loading"), fontSize = 12.sp)
            else -> {}
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                onAdd(code, label, method, expected.takeIf { it.isNotBlank() }, severity)
            }) { Text(skill.t("admin.standard.point.add")) }
            if (selectedPoint != null) {
                OutlinedButton(onClick = {
                    onUpdate(
                        selectedPoint.id, code, label, method,
                        expected.takeIf { it.isNotBlank() }, severity,
                    )
                }) { Text(skill.t("admin.standard.point.save_edit")) }
            }
        }
    }
}

@Composable
private fun CategoryConfirmationPanel(
    skill: com.giraffetechnology.qc.contracts.GiraffeLanguageSkill,
    state: AdminCategoryState,
    selectedPointId: String?,
    onConfirm: (String, String) -> Unit,
) {
    val loaded = state as? AdminCategoryState.Loaded
    var menuOpen by remember { mutableStateOf(false) }
    var category by remember(selectedPointId, loaded) {
        mutableStateOf(
            selectedPointId?.let { loaded?.byPointId?.get(it)?.confirmedCategory }
                ?: selectedPointId?.let { loaded?.byPointId?.get(it)?.proposedCategory }
                ?: ""
        )
    }
    Spacer(Modifier.height(8.dp))
    Text(skill.t("admin.standard.category.title"), fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
    when (state) {
        AdminCategoryState.Loading, AdminCategoryState.Confirming ->
            Text(skill.t("admin.standard.category.loading"), fontSize = 12.sp)
        is AdminCategoryState.Error -> AdminErrorBanner(skill.t(state.message))
        else -> Unit
    }
    if (loaded != null && selectedPointId != null) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column {
                OutlinedButton(onClick = { menuOpen = true }) {
                    Text(category.ifEmpty { skill.t("admin.standard.category.select") })
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    loaded.options.forEach { option ->
                        DropdownMenuItem(
                            text = { Text("${option.category} · ${option.defaultAiRole}") },
                            onClick = { category = option.category; menuOpen = false },
                        )
                    }
                }
            }
            Button(
                enabled = category.isNotBlank(),
                onClick = { onConfirm(selectedPointId, category) },
            ) { Text(skill.t("admin.standard.category.confirm")) }
        }
        val current = loaded.byPointId[selectedPointId]
        if (current?.confirmedCategory != null) {
            Text(
                skill.t(
                    "admin.standard.category.confirmed_by",
                    mapOf(
                        "actor" to (current.confirmedBy ?: skill.t("welcome.administrator")),
                        "role" to current.aiRole,
                    ),
                ),
                fontSize = 11.sp,
            )
        }
    }
}

/**
 * Region drawing canvas (WS3 item 5) — a real drag-to-draw bounding-box editor.
 * Drawn boxes are normalized to 0–1 image coordinates so they serialize
 * directly into the backend's `{image_id, x, y, w, h}` region model.
 */
@Composable
fun RegionEditorCanvas(
    imageUrl: String,
    imageId: String,
    cookie: String?,
    existing: List<Region>,
    onRegionDrawn: (Region) -> Unit,
) {
    var canvasSize by remember { mutableStateOf(Size.Zero) }
    var dragStart by remember { mutableStateOf<Offset?>(null) }
    var dragCurrent by remember { mutableStateOf<Offset?>(null) }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(260.dp)
            .onSizeChanged { canvasSize = Size(it.width.toFloat(), it.height.toFloat()) },
    ) {
        RemoteImage(url = imageUrl, cookie = cookie, modifier = Modifier.fillMaxSize())

        Canvas(
            modifier = Modifier
                .fillMaxSize()
                .pointerInput(imageId) {
                    detectDragGestures(
                        onDragStart = { offset ->
                            dragStart = offset
                            dragCurrent = offset
                        },
                        onDrag = { change, _ ->
                            change.consume()
                            dragCurrent = change.position
                        },
                        onDragEnd = {
                            val start = dragStart
                            val end = dragCurrent
                            if (start != null && end != null && canvasSize.width > 0f) {
                                val x0 = minOf(start.x, end.x).coerceIn(0f, canvasSize.width)
                                val y0 = minOf(start.y, end.y).coerceIn(0f, canvasSize.height)
                                val x1 = maxOf(start.x, end.x).coerceIn(0f, canvasSize.width)
                                val y1 = maxOf(start.y, end.y).coerceIn(0f, canvasSize.height)
                                val w = (x1 - x0) / canvasSize.width
                                val h = (y1 - y0) / canvasSize.height
                                if (w > 0.005f && h > 0.005f) {
                                    onRegionDrawn(
                                        Region(
                                            imageId = imageId,
                                            x = x0 / canvasSize.width,
                                            y = y0 / canvasSize.height,
                                            w = w,
                                            h = h,
                                        )
                                    )
                                }
                            }
                            dragStart = null
                            dragCurrent = null
                        },
                    )
                },
        ) {
            existing.forEach { r ->
                drawRect(
                    color = Color(0xFF2E7D32),
                    topLeft = Offset(r.x * size.width, r.y * size.height),
                    size = Size(r.w * size.width, r.h * size.height),
                    style = Stroke(width = 3f),
                )
            }
            val start = dragStart
            val current = dragCurrent
            if (start != null && current != null) {
                drawRect(
                    color = Color(0xFF1565C0),
                    topLeft = Offset(minOf(start.x, current.x), minOf(start.y, current.y)),
                    size = Size(
                        kotlin.math.abs(current.x - start.x),
                        kotlin.math.abs(current.y - start.y),
                    ),
                    style = Stroke(width = 3f),
                )
            }
        }
    }
}
