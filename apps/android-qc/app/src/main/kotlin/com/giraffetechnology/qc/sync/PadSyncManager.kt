package com.giraffetechnology.qc.sync

import android.content.Context
import android.util.Log
import com.giraffetechnology.qc.store.PadSqliteHelper
import com.giraffetechnology.qc.store.SqliteOutboxStore
import com.giraffetechnology.qc.store.SqliteStandardStore
import java.io.File
import java.util.Base64

/**
 * Wires the Task 03 offline-sync components together on the Pad:
 *   - [SqliteStandardStore] (imported standards) + [SqliteOutboxStore] (results),
 *   - [BundleImporter] with the shipped Ed25519 public key asset,
 *   - [InboxScanner] (USB sideload) and [OutboxUploader] (sync-window upload).
 *
 * The public key is read from `assets/qc_bundle_public_key.b64` (raw 32-byte key,
 * base64) and can be replaced via an app update. There is no "skip verification"
 * path in this build (Hard Constraint 3).
 *
 * Nothing here runs during inspection; the sync methods are only invoked from a
 * user-initiated sync action or an inbox scan.
 */
class PadSyncManager(
    context: Context,
    private val serverBaseUrl: String,
    inboxPath: String = InboxScanner.DEFAULT_INBOX_PATH,
    private val syncClientFactory: (String) -> BundleSyncClient = { HttpBundleSyncClient(it) },
) {
    private val appContext = context.applicationContext
    private val helper = PadSqliteHelper(appContext)

    val standardStore = SqliteStandardStore(helper)
    val outboxStore = SqliteOutboxStore(helper)

    private val publicKey: ByteArray by lazy { loadPublicKeyAsset() }

    private val photoRoot = File(appContext.filesDir, "standards")

    val importer = BundleImporter(
        store = standardStore,
        publicKey = { publicKey },
        photoRoot = photoRoot,
        audit = { rec -> Log.i(TAG, "bundle audit: $rec") },
    )

    val inboxScanner = InboxScanner(File(inboxPath), importer)

    /** USB-sideload intake: scan the inbox directory once. */
    fun scanInbox(): List<InboxScanner.ScanOutcome> = inboxScanner.scanOnce()

    /** Sync-window pull: version check → download → import (returns null if up to date). */
    suspend fun pullLatest(tenantId: String, lineScope: String = ""): ImportResult? {
        val client = syncClientFactory(serverBaseUrl)
        val serverVersion = client.latestBundleVersion(tenantId, lineScope) ?: return null
        val installed = standardStore.installedBundleVersion(tenantId, lineScope)
        if (installed != null && serverVersion <= installed) return null
        val archive = client.downloadLatest(tenantId, lineScope) ?: return null
        return importer.import(archive, source = "sync_pull")
    }

    /** Sync-window push: drain the result outbox to the server. */
    suspend fun uploadOutbox(tenantId: String): UploadSummary =
        OutboxUploader(outboxStore, syncClientFactory(serverBaseUrl)).sync(tenantId)

    private fun loadPublicKeyAsset(): ByteArray {
        val b64 = appContext.assets.open(PUBLIC_KEY_ASSET).bufferedReader().use { it.readText().trim() }
        return Base64.getDecoder().decode(b64)
    }

    companion object {
        private const val TAG = "PadSyncManager"
        const val PUBLIC_KEY_ASSET = "qc_bundle_public_key.b64"
    }
}
