package com.giraffetechnology.qc.contracts

/**
 * Android on-device local standards store (PRD §14 — Pad Local Standards).
 *
 * S0 deliverable (in-app copy). S5/S6 implement this interface against SQLite;
 * it is the only surface the Pad UI reads installed standards through. All
 * lookups are strictly offline — they never touch the network. A miss returns
 * null / empty (never an exception), so callers can fail closed.
 *
 * The data classes below carry every PRD §5.4 detection-point field verbatim so
 * an installed revision is self-sufficient for on-device inspection with no
 * server round-trip. Field names and the [DetectionPoint]/[DetectionSeverity]/
 * [RequiredView]/[IncidentalFindingPolicy] shapes match the API contract
 * (`contracts/openapi.yaml`) and the bundle manifest.
 */
interface SqliteStandardStore {

    /**
     * Search installed SKUs by item number or name (case-insensitive,
     * substring). Returns the lightweight [InstalledSku] rows without their
     * detection points. Empty list when nothing matches.
     */
    suspend fun searchInstalledSku(query: String): List<InstalledSku>

    /** Fetch one installed SKU by id, or null if not installed on this Pad. */
    suspend fun getInstalledSku(skuId: String): InstalledSku?

    /**
     * Fetch the currently-installed active standard revision for a SKU,
     * including its full detection-point set. Null if the SKU is not installed
     * or has no active revision.
     */
    suspend fun getInstalledStandardRevision(skuId: String): InstalledStandardRevision?
}

/**
 * True when this Pad has at least one SKU installed at all. Kept as an interface
 * extension so every implementation (SQLite / in-memory) shares one definition
 * of "has any standards", which the operator task-selection screen uses to pick
 * between the empty-store message and the not-found message.
 */
suspend fun SqliteStandardStore.hasAnyInstalledStandards(): Boolean =
    searchInstalledSku("").isNotEmpty()

/** Lightweight installed-SKU header (no detection points). */
data class InstalledSku(
    val skuId: String,
    val itemNumber: String,
    val name: String,
    /** Wire value from [StandardState]; the SKU's state on this Pad. */
    val state: String,
    val activeStandardRevisionId: String?,
    /** Bundle this SKU was installed from (PRD §7 provenance). */
    val bundleId: String?,
    val bundleVersion: String?,
)

/** An installed standard revision with its complete detection-point set. */
data class InstalledStandardRevision(
    val standardRevisionId: String,
    val skuId: String,
    val revisionNo: Int,
    /** Wire value from [StandardState]. */
    val state: String,
    /** Local file paths of installed standard reference photos. */
    val standardPhotoPaths: List<String>,
    val detectionPoints: List<DetectionPoint>,
    /** Source bundle provenance for audit (PRD §7). */
    val bundleId: String,
    val bundleVersion: String,
)

/**
 * Canonical detection point (PRD §5.4), plus the optional WS6 region extension,
 * carried verbatim through the API, bundle manifest, and this store.
 */
data class DetectionPoint(
    val pointCode: String,
    val label: String,
    val description: String,
    val methodHint: String,
    /** e.g. "3" for a count checkpoint; null when not applicable. */
    val expectedValue: String?,
    val passCriteria: String,
    val severity: DetectionSeverity,
    val requiredView: RequiredView,
    val evidenceRequired: Boolean,
    val incidentalFindingPolicy: IncidentalFindingPolicy,
    /** Studio-authored normalized crop regions carried by the signed Bundle. */
    val regions: List<DetectionPointRegion> = emptyList(),
)

data class DetectionPointRegion(
    val imageId: String,
    val x: Double,
    val y: Double,
    val w: Double,
    val h: Double,
)

enum class DetectionSeverity(val wire: String) {
    MINOR("minor"), MAJOR("major"), CRITICAL("critical");

    companion object {
        fun fromWire(v: String): DetectionSeverity? = entries.firstOrNull { it.wire == v }
    }
}

enum class RequiredView(val wire: String) {
    FRONT("front"),
    BACK("back"),
    LEFT_SIDE("left_side"),
    RIGHT_SIDE("right_side"),
    TOP("top"),
    BOTTOM("bottom"),
    INTERIOR("interior"),
    DETAIL("detail"),
    ANY("any");

    companion object {
        fun fromWire(v: String): RequiredView? = entries.firstOrNull { it.wire == v }
    }
}

enum class IncidentalFindingPolicy(val wire: String) {
    /** Default: any incidental finding here escalates the item to review. */
    FLAG_FOR_REVIEW("flag_for_review"),
    /** Record the finding in the report but do not change the verdict. */
    RECORD_ONLY("record_only"),
    /** Ignore incidental findings for this checkpoint. */
    IGNORE("ignore");

    companion object {
        fun fromWire(v: String): IncidentalFindingPolicy? = entries.firstOrNull { it.wire == v }
    }
}
