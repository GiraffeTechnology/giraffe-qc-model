package com.giraffetechnology.qc.operator

import com.giraffetechnology.qc.contracts.InstalledSku
import com.giraffetechnology.qc.contracts.InstalledStandardRevision
import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import com.giraffetechnology.qc.sku.Sku

/**
 * Maps the offline store's installed types onto the existing inspection data
 * contract ([Sku] + qwen input types) so a locally-selected standard flows into
 * the same [com.giraffetechnology.qc.sku.PadInspectionCoordinator] path used by
 * the backend-search flow — no second inspection pipeline.
 */
object InstalledStandardMapper {

    fun toSku(installed: InstalledSku, revision: InstalledStandardRevision?): Sku = Sku(
        id = installed.skuId,
        itemNumber = installed.itemNumber,
        name = installed.name,
        standardPhotoPath = revision?.standardPhotoPaths?.firstOrNull(),
        referenceImageUrl = null,
        activeStandardRevisionId = installed.activeStandardRevisionId,
        standardPhotos = revision?.standardPhotoPaths?.mapIndexed { i, path ->
            StandardPhotoInput(photoId = "$i", localPath = path, angle = null)
        } ?: emptyList(),
        detectionPoints = revision?.detectionPoints?.map { p ->
            QcPointInput(
                qcPointId = p.pointCode,
                qcPointCode = p.pointCode,
                name = p.label,
                description = p.description,
                roiJson = null,
                ruleType = p.methodHint.ifBlank { null },
            )
        } ?: emptyList(),
    )
}
