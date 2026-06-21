package com.giraffetechnology.qc

import android.content.Context
import com.giraffetechnology.qc.qwen.MnnRuntimeLoader

// Singleton entry point for MnnRuntimeLoader in production code.
// Only PadRuntimeGraph may instantiate MnnRuntimeLoader — never call
// MnnRuntimeLoader(context) directly from Activities or Controllers.
object PadRuntimeGraph {
    @Volatile private var _loader: MnnRuntimeLoader? = null

    fun init(context: Context) {
        if (_loader == null) {
            synchronized(this) {
                if (_loader == null) {
                    _loader = MnnRuntimeLoader(context.applicationContext)
                }
            }
        }
    }

    val runtimeLoader: MnnRuntimeLoader
        get() = checkNotNull(_loader) {
            "PadRuntimeGraph.init(context) must be called before accessing runtimeLoader"
        }
}
