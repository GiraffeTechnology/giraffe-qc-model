package com.giraffetechnology.qc

import android.content.Context
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader

object PadRuntimeGraph {

    @Volatile private var _loader: MnnRuntimeLoader? = null

    fun init(context: Context) {
        if (_loader == null) {
            _loader = MnnRuntimeLoader(context.applicationContext)
        }
    }

    val runtimeLoader: MnnRuntimeLoader
        get() = checkNotNull(_loader) {
            "PadRuntimeGraph.init(context) must be called before accessing runtimeLoader"
        }
}
