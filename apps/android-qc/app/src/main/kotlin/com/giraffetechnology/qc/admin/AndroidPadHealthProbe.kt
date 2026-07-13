package com.giraffetechnology.qc.admin

import android.content.Context
import android.os.StatFs
import com.giraffetechnology.qc.BuildConfig

/**
 * Real on-device health probe backing the Pad panel of the admin health
 * screen: filesystem stats from the app's data volume plus build identity.
 */
class AndroidPadHealthProbe(context: Context) : PadHealthProbe {

    private val dataDirPath: String = context.applicationContext.filesDir.absolutePath

    override fun diskFreeBytes(): Long = StatFs(dataDirPath).availableBytes

    override fun diskTotalBytes(): Long = StatFs(dataDirPath).totalBytes

    override fun appVersionName(): String = BuildConfig.VERSION_NAME

    override fun buildProvenance(): String {
        // WS1 adds GIT_COMMIT_SHA / GIT_BRANCH / BUILD_TIMESTAMP BuildConfig
        // fields; read them reflectively so this branch builds both before and
        // after WS1 merges (merge order is WS1 → WS3).
        fun field(name: String): String? = runCatching {
            BuildConfig::class.java.getField(name).get(null) as? String
        }.getOrNull()
        val sha = field("GIT_COMMIT_SHA")
        val branch = field("GIT_BRANCH")
        val ts = field("BUILD_TIMESTAMP")
        return if (sha != null) {
            "commit=${sha.take(12)} branch=${branch ?: "?"} builtAt=${ts ?: "?"}"
        } else {
            "version=${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})"
        }
    }
}
