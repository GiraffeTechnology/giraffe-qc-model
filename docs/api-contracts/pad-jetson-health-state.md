# Pad-Side Jetson + Pad Health State — API Contract

**Owner:** WS4 (`claude/ws4-operator-jetson-integration`). **Consumed by:**
Account A's WS3 admin health screen (via the already-existing server sync
surface, § 3 — no new server endpoint needed).

**Status: implemented in the WS4 round**, with one honest gap: § 3's health
relay is wired (`JetsonServerRelay`), but the *pairing/bindings* relay
(`POST /api/qc/jetson/bindings`) is **not** — it needs a `workstation_id`
this scaffold has no clean source for at pairing time. `PadReadiness.kt` (the
retired MNN-era readiness resolver) was kept, not deleted, and still backs
the legacy MNN path behind `PadRuntimeConfig.legacyMnnRuntimeEnabled` — the
new `JetsonPadReadiness.kt` (§ 2) is the one actually used by default. See
§ 3 and § 4 below for the as-built detail.

## 1. Design goals

1. Mirror `jetson-runner-api.md` § 3's readiness enum exactly — the Pad,
   Jetson, and Server must agree on state *strings*, not just concepts.
2. Work **offline**: the Pad polls the Jetson directly over LAN and can
   compute its own readiness state without the Server being reachable
   ("floor first, sync later" — same principle as pairing). The Server-relay
   path (§ 3) is for admin fleet visibility, not a dependency for the
   Operator's fail-closed gate.
3. Give WS3's admin screen one clear place to read fleet health from — the
   already-existing `GET /api/qc/jetson/runners` / `GET
   /api/qc/jetson/runners/{id}` (§ 3) — so WS3 needs no new server work.

## 2. Kotlin state model `[EXISTS]`

Split across two packages, as built:
`com.giraffetechnology.qc.jetson` (`JetsonReadinessState`, `JetsonHealthSnapshot`,
`PadJetsonState`, `PairingState` — `JetsonHealthState.kt`) and
`com.giraffetechnology.qc.readiness` (`JetsonPadReadiness.kt`, the Jetson-worded
counterpart to the legacy `PadReadiness.kt`, both sharing the existing
`PadReadinessInputs`/`PadReadinessView` shape rather than introducing a third
readiness-view type). `PadReadiness.kt` itself was **not deleted** — it still
backs the legacy MNN path.

```kotlin
/** Mirrors jetson-runner-api.md §3 exactly — same state strings as Jetson/Server. */
enum class JetsonReadinessState(val wireValue: String) {
    READY("jetson_ready"),
    CONNECTING("jetson_connecting"),
    UNREACHABLE("jetson_unreachable"),
    NO_STANDARD_INSTALLED("no_standard_installed"),
    NO_SKU_SELECTED("no_sku_selected");

    val canSubmitInspection: Boolean get() = this == READY
}

/** Raw poll of the Jetson's GET /health (jetson-runner-api.md §1.1). */
data class JetsonHealthSnapshot(
    val serviceUp: Boolean,
    val modelLoaded: Boolean,
    val temperatureC: Double?,
    val throttling: Boolean?,
    val diskFreePercent: Double?,
    val lastInferenceLatencyMs: Int?,
    val readinessState: JetsonReadinessState,
    val jetsonDeviceId: String,
    val agentVersion: String,
    val adapterName: String?,   // as-built addition: which adapter served this (mock | llama_cpp)
    val modelName: String?,     // as-built addition
    val polledAtEpochMs: Long,  // as-built: epoch millis, not java.time.Instant
    /** True if this snapshot is from JETSON_MOCK_MODE=true — must be surfaced
     *  in the UI per the mock-labeling ground rule, never silently hidden. */
    val isMock: Boolean,
)

/** What the Operator work screen and WS3's admin screen both bind to. */
data class PadJetsonState(
    val pairing: PairingState,          // Unpaired | Pairing | Paired(jetsonDeviceId)
    val lastHealth: JetsonHealthSnapshot?,   // null before the first successful poll
    val readiness: JetsonReadinessState,     // combines pairing + health + SKU/standard selection
    val canSubmitInspection: Boolean,        // fail-closed gate WS4 §1.6 reads this directly
)

sealed class PairingState {
    object Unpaired : PairingState()
    data class Pairing(val path: String) : PairingState()   // "usb" | "wifi"
    data class Paired(val jetsonDeviceId: String, val pairingPath: String) : PairingState()
}
```

`PadJetsonState.readiness` resolution must match the priority order implied
by `jetson-runner-api.md` § 3 (no SKU/standard selected takes precedence over
a merely-connecting Jetson, since those are prerequisites the operator can fix
without touching the Jetson at all) — WS4 should port the exact priority logic
from `service.resolve_readiness` (`src/qc_model/jetson/service.py`) rather
than re-deriving it, so Pad-local and Server-side readiness computation can't
drift.

## 3. Relay to Server (existing endpoints — no server change needed)

The Pad polls the Jetson's `GET /health` on its own cadence (WS4 to decide;
match whatever polling interval pattern the app already uses elsewhere for
consistency — do not invent a new one). On each successful poll, and on every
pairing state change, the Pad relays to the Server **best-effort, non-
blocking**:

- Pairing completed/changed → `POST /api/qc/jetson/bindings`
  (`jetson-runner-api.md` § 5) with `pad_device_id`, `jetson_device_id`,
  `pubkey_fingerprint`, `workstation_id`, `pairing_path`.
- Health snapshot → `POST /api/qc/jetson/runners/{jetson_device_id}/health`
  with the fields from `JetsonHealthSnapshot` (field names already match the
  server's `HealthBody` schema 1:1 — no translation layer needed beyond
  Kotlin↔JSON serialization).

Relay failures (Server unreachable) must **not** affect `PadJetsonState` or
the fail-closed gate — those are computed from the Pad's direct LAN view of
the Jetson only. The relay is purely so `GET /api/qc/jetson/runners` (already
implemented, `jetson-runner-api.md` § 5) has fresh data for WS3's admin
screen; a stale/missing relay degrades admin *visibility*, never Operator
*safety*.

## 4. What WS3 reads (already exists, listed here for cross-reference only)

WS3's admin health screen should bind to `GET /api/qc/jetson/runners`
(fleet list) and `GET /api/qc/jetson/runners/{jetson_device_id}` (detail) on
the Server — both already implemented in `src/api/jetson_router.py`. WS3
needs **no new backend work** for this; it is consuming what WS5 already
shipped in PR #51. If WS3's screen needs a field the current `runner_view`
doesn't return, that's a WS3-initiated contract change and should be raised
against WS5, not assumed.
