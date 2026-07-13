package com.giraffetechnology.qc.jetson

import org.junit.Test

/**
 * The relay's core contract is "never throws, never blocks the caller on
 * failure" (docs/api-contracts/pad-jetson-health-state.md §3: a stale/missing
 * relay must degrade admin visibility, never Operator safety). Full HTTP
 * behavior isn't covered here (no injectable transport for this
 * intentionally-minimal best-effort utility -- see class doc); this asserts
 * the one property that matters most: unreachable/invalid targets never
 * propagate an exception to the caller.
 */
class JetsonServerRelayTest {

    private fun health() = JetsonHealthSnapshot(
        serviceUp = true,
        modelLoaded = true,
        temperatureC = 60.0,
        throttling = false,
        diskFreePercent = 70.0,
        lastInferenceLatencyMs = 300,
        readinessState = JetsonReadinessState.READY,
        jetsonDeviceId = "jetson-1",
        agentVersion = "0.2.0",
        adapterName = "mock",
        modelName = "mock-deterministic",
        polledAtEpochMs = 0L,
        isMock = true,
    )

    @Test
    fun `relayHealth never throws when the server is unreachable`() {
        val relay = JetsonServerRelay("http://127.0.0.1:1", connectTimeoutMs = 200, readTimeoutMs = 200)
        relay.relayHealth("default", health())
    }

    @Test
    fun `relayHealth is a no-op when jetson device id is blank`() {
        val relay = JetsonServerRelay("http://127.0.0.1:1", connectTimeoutMs = 200, readTimeoutMs = 200)
        relay.relayHealth("default", health().copy(jetsonDeviceId = ""))
    }

    @Test
    fun `relayHealth never throws for a malformed base url`() {
        val relay = JetsonServerRelay("not a url", connectTimeoutMs = 200, readTimeoutMs = 200)
        relay.relayHealth("default", health())
    }
}
