package com.giraffetechnology.qc.sync

import com.giraffetechnology.qc.qwen.QcPointInput
import com.giraffetechnology.qc.qwen.StandardPhotoInput
import com.giraffetechnology.qc.sku.Sku

/**
 * In-memory [StandardStore] for JVM unit tests. [installBundle] is all-or-nothing
 * and can be told to fail mid-import to exercise the importer's rollback path.
 */
class InMemoryStandardStore : StandardStore {
    private data class Scope(val tenant: String, val line: String)
    private val versions = HashMap<Scope, Int>()
    private val skusByTenant = HashMap<String, MutableMap<String, Sku>>()

    /** When set, installBundle throws after clearing — proves rollback keeps prior state. */
    var failOnInstall = false

    override fun installedBundleVersion(tenantId: String, lineScope: String): Int? =
        versions[Scope(tenantId, lineScope)]

    override fun installBundle(manifest: BundleManifest, photoLocalPaths: Map<String, String>) {
        val scope = Scope(manifest.tenantId, manifest.lineScope)
        // Snapshot for rollback.
        val prevVersion = versions[scope]
        val prevSkus = skusByTenant[manifest.tenantId]?.toMutableMap()
        try {
            val map = skusByTenant.getOrPut(manifest.tenantId) { HashMap() }
            map.clear()
            if (failOnInstall) throw RuntimeException("simulated install failure")
            for (s in manifest.skus) {
                map[s.skuId] = Sku(
                    id = s.skuId, itemNumber = s.itemNumber, name = s.name,
                    activeStandardRevisionId = s.activeStandardRevisionId,
                    standardPhotos = s.photos.map {
                        StandardPhotoInput(it.id, photoLocalPaths.getValue(it.id), it.angle)
                    },
                    detectionPoints = s.detectionPoints.map {
                        QcPointInput(it.id, it.pointCode, it.label, it.description ?: "", it.roiJson, it.methodHint)
                    },
                )
            }
            versions[scope] = manifest.bundleVersion
        } catch (e: Exception) {
            // Roll back to the snapshot.
            if (prevSkus != null) skusByTenant[manifest.tenantId] = prevSkus else skusByTenant.remove(manifest.tenantId)
            if (prevVersion != null) versions[scope] = prevVersion else versions.remove(scope)
            throw e
        }
    }

    override fun listSkus(tenantId: String): List<Sku> =
        skusByTenant[tenantId]?.values?.sortedBy { it.itemNumber } ?: emptyList()

    override fun getSku(tenantId: String, skuId: String): Sku? = skusByTenant[tenantId]?.get(skuId)

    override fun findByItemNumber(tenantId: String, query: String): List<Sku> =
        listSkus(tenantId).filter { it.itemNumber.contains(query) }
}

/** In-memory [OutboxStore] for JVM unit tests. */
class InMemoryOutboxStore : OutboxStore {
    private val jobs = LinkedHashMap<String, OutboxJob>()
    private var lastSync: Long? = null

    override fun enqueue(job: OutboxJob) {
        if (!jobs.containsKey(job.jobUuid)) jobs[job.jobUuid] = job.copy(status = "pending")
    }

    override fun pending(limit: Int): List<OutboxJob> =
        jobs.values.filter { it.status == "pending" }.take(limit)

    override fun markUploaded(jobUuid: String) {
        jobs[jobUuid]?.let { jobs[jobUuid] = it.copy(status = "uploaded") }
    }

    override fun markFailed(jobUuid: String, reason: String) {
        jobs[jobUuid]?.let { jobs[jobUuid] = it.copy(status = "failed", attempts = it.attempts + 1) }
    }

    override fun counts(): OutboxCounts = OutboxCounts(
        pending = jobs.values.count { it.status == "pending" },
        uploaded = jobs.values.count { it.status == "uploaded" },
        failed = jobs.values.count { it.status == "failed" },
        lastSyncAtMs = lastSync,
    )

    override fun setLastSyncAt(tsMs: Long) { lastSync = tsMs }
}

/**
 * Fake [BundleSyncClient] modelling the server's idempotent dedupe: a UUID seen
 * before returns "duplicate". Can be told to fail after N jobs to exercise resume.
 */
class FakeSyncClient(
    private val rejectUuids: Set<String> = emptySet(),
    private var failAfter: Int = Int.MAX_VALUE,
) : BundleSyncClient {
    val seen = HashSet<String>()
    var latest: Int? = null
    var archive: ByteArray? = null

    override suspend fun latestBundleVersion(tenantId: String, lineScope: String): Int? = latest
    override suspend fun downloadLatest(tenantId: String, lineScope: String): ByteArray? = archive

    override suspend fun uploadBatch(tenantId: String, jobs: List<OutboxJob>): List<UploadJobOutcome> {
        val out = ArrayList<UploadJobOutcome>()
        for (job in jobs) {
            if (failAfter <= 0) throw java.io.IOException("simulated network failure")
            failAfter--
            when {
                job.jobUuid in rejectUuids -> out.add(UploadJobOutcome(job.jobUuid, "rejected", "unknown sku"))
                !seen.add(job.jobUuid) -> out.add(UploadJobOutcome(job.jobUuid, "duplicate"))
                else -> out.add(UploadJobOutcome(job.jobUuid, "created"))
            }
        }
        return out
    }
}
