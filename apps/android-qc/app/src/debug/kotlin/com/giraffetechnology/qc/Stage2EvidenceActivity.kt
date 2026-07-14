package com.giraffetechnology.qc

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

const val STAGE2_MOCK_LABEL = "NON-PRODUCTION MOCK"

data class Stage2EvidenceState(
    val id: String,
    val heading: String,
    val status: String,
    val detail: String,
    val tone: String,
    val showFixture: Boolean = false,
    val failClosed: Boolean = false,
    val resultCount: Int = 0,
)

fun stage2EvidenceState(id: String): Stage2EvidenceState = when (id) {
    "simulator-ready" -> Stage2EvidenceState(
        id, "ARM64 simulator ready", "READY",
        "QEMU aarch64 guest verified · external-drive-backed session", "success",
    )
    "simulated-capture" -> Stage2EvidenceState(
        id, "Simulated capture", "FIXTURE LOADED",
        "tests/fixtures/qc/capture_red_square_pass.png · camera not connected", "info",
        showFixture = true,
    )
    "cv-success" -> Stage2EvidenceState(
        id, "Standalone CV evidence", "CV COMPLETE",
        "Normalized 200 × 200 · evidence informational only · no autonomous final verdict",
        "success", showFixture = true, resultCount = 1,
    )
    "cv-anomaly" -> Stage2EvidenceState(
        id, "Insufficient CV evidence", "REVIEW REQUIRED",
        "Invalid or incomplete evidence is blocked; silent pass is forbidden", "warning",
        showFixture = true, failClosed = true,
    )
    "simulator-unavailable" -> Stage2EvidenceState(
        id, "Simulator unavailable", "BLOCKED",
        "SIMULATOR_UNAVAILABLE · mount/dependency readiness failed", "error",
        failClosed = true,
    )
    "refresh-retry" -> Stage2EvidenceState(
        id, "Simulator recovered", "RETRY COMPLETE",
        "Dependency restored · exactly one result retained · no duplicate result", "success",
        resultCount = 1,
    )
    else -> Stage2EvidenceState(
        id, "Unknown evidence state", "BLOCKED", "UNKNOWN_STAGE2_UI_STATE", "error",
        failClosed = true,
    )
}

class Stage2EvidenceActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val state = stage2EvidenceState(intent.getStringExtra("state") ?: "simulator-unavailable")
        Log.i(
            "Stage2Evidence",
            "state=${state.id} inference_calls=0 result_count=${state.resultCount} fail_closed=${state.failClosed}",
        )
        setContent { MaterialTheme { Stage2EvidenceScreen(state) } }
    }
}

@Composable
fun Stage2EvidenceScreen(state: Stage2EvidenceState) {
    val accent = when (state.tone) {
        "success" -> Color(0xFF15803D)
        "warning" -> Color(0xFFB45309)
        "error" -> Color(0xFFB91C1C)
        else -> Color(0xFF1D4ED8)
    }
    Surface(modifier = Modifier.fillMaxSize(), color = Color(0xFFF5F7FA)) {
        Column(modifier = Modifier.fillMaxSize().padding(28.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Giraffe QC · Stage 2", fontSize = 26.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.weight(1f))
                Text(
                    STAGE2_MOCK_LABEL,
                    color = Color.White,
                    fontWeight = FontWeight.ExtraBold,
                    modifier = Modifier.background(Color(0xFFB91C1C)).padding(12.dp),
                )
            }
            Spacer(Modifier.height(24.dp))
            Row(modifier = Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Box(
                    modifier = Modifier.weight(3f).fillMaxHeight().background(Color.White)
                        .border(2.dp, Color(0xFFD1D5DB)).padding(20.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    if (state.showFixture) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Image(
                                painter = painterResource(R.drawable.stage2_mock_capture),
                                contentDescription = "Simulated red-square capture fixture",
                                modifier = Modifier.weight(1f).fillMaxWidth(),
                            )
                            Text("SIMULATED FIXTURE · NO CAMERA", fontWeight = FontWeight.Bold)
                        }
                    } else {
                        Text("No live camera feed", color = Color(0xFF6B7280), fontSize = 22.sp)
                    }
                }
                Column(
                    modifier = Modifier.weight(2f).fillMaxHeight().background(Color.White)
                        .border(2.dp, Color(0xFFD1D5DB)).padding(24.dp),
                ) {
                    Text(state.heading, fontSize = 25.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(18.dp))
                    Text(
                        state.status,
                        color = accent,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.ExtraBold,
                        modifier = Modifier.fillMaxWidth().background(accent.copy(alpha = 0.12f)).padding(16.dp),
                    )
                    Spacer(Modifier.height(18.dp))
                    Text(state.detail, fontSize = 17.sp, lineHeight = 25.sp)
                    Spacer(Modifier.height(18.dp))
                    Text("Method: QEMU aarch64", fontWeight = FontWeight.SemiBold)
                    Text("Inference calls: 0")
                    Text("Result count: ${state.resultCount}")
                    Text("Fail closed: ${if (state.failClosed) "YES" else "not triggered"}")
                    Spacer(Modifier.weight(1f))
                    Text("State ID: ${state.id}", color = Color(0xFF6B7280), fontSize = 13.sp)
                }
            }
        }
    }
}
