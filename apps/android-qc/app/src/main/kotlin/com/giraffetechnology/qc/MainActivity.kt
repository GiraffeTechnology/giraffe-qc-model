package com.giraffetechnology.qc

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.giraffetechnology.qc.sku.MnnRuntimeState

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PadRuntimeGraph.init(this)
        setContent {
            val runtimeState by PadRuntimeGraph.runtimeLoader.runtimeState.collectAsState()
            MaterialTheme {
                Scaffold { padding ->
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(padding),
                        contentAlignment = Alignment.Center,
                    ) {
                        when (runtimeState) {
                            is MnnRuntimeState.Ready    -> Text("Giraffe QC — Ready")
                            is MnnRuntimeState.Loading  -> Text("MNN loading…")
                            is MnnRuntimeState.NotReady -> Text("Local runtime not ready")
                        }
                    }
                }
            }
        }
    }
}
