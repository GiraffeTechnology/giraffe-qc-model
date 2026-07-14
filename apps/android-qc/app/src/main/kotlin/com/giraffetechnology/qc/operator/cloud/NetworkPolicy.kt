package com.giraffetechnology.qc.operator.cloud

/** Pure, deterministic implementation of the v2 Wi-Fi/cellular policy. */
class NetworkPolicy(private val config: NetworkPolicyConfig = NetworkPolicyConfig()) {
    private val wifi = ArrayDeque<LinkSample>()
    private val cellular = ArrayDeque<LinkSample>()
    private var selected = OperatorNetwork.NONE
    private var activeJobNetwork: OperatorNetwork? = null
    private var deferred: OperatorNetwork? = null
    private var wifiHealthySinceMs: Long? = null

    fun observe(sample: LinkSample): NetworkDecision {
        val samples = if (sample.network == OperatorNetwork.WIFI) wifi else cellular
        samples.addLast(sample)
        while (samples.size > config.sampleWindowSize) samples.removeFirst()
        return decide(sample.observedAtMs)
    }

    fun beginJob(): OperatorNetwork {
        check(activeJobNetwork == null) { "a cloud job already owns the network" }
        activeJobNetwork = selected
        return selected
    }

    fun endJob(): NetworkDecision {
        activeJobNetwork = null
        deferred?.let { selected = it }
        deferred = null
        return decide(System.currentTimeMillis())
    }

    fun activeJobNetwork(): OperatorNetwork? = activeJobNetwork
    fun switchDeferredUntilJobEnd(): Boolean = deferred != null
    fun currentNetwork(): OperatorNetwork = selected

    private fun decide(nowMs: Long): NetworkDecision {
        val wifiBreaches = breaches(wifi)
        val cellularBreaches = breaches(cellular)
        val wifiReady = wifi.size >= config.sampleWindowSize && wifiBreaches.isEmpty()
        val cellularReady = cellular.isNotEmpty() && cellularBreaches.isEmpty()

        val desired = when {
            selected == OperatorNetwork.CELLULAR && wifiReady && wifiAverageUplink() > config.wifiReturnMinUplinkMbps -> {
                val since = wifiHealthySinceMs ?: nowMs.also { wifiHealthySinceMs = it }
                if (nowMs - since >= config.wifiReturnSustainMs) OperatorNetwork.WIFI else OperatorNetwork.CELLULAR
            }
            wifiReady -> OperatorNetwork.WIFI
            cellularReady -> OperatorNetwork.CELLULAR
            else -> OperatorNetwork.NONE
        }
        if (!wifiReady) wifiHealthySinceMs = null

        val old = selected
        if (activeJobNetwork != null && desired != old) deferred = desired else selected = desired
        val effective = if (activeJobNetwork != null) old else selected
        val effectiveBreaches = when (effective) {
            OperatorNetwork.WIFI -> wifiBreaches
            OperatorNetwork.CELLULAR -> cellularBreaches
            OperatorNetwork.NONE -> (wifiBreaches + cellularBreaches + "no_cellular_available").distinct()
        }
        return NetworkDecision(
            selected = effective,
            breaches = effectiveBreaches,
            switched = activeJobNetwork == null && old != selected,
            reason = effectiveBreaches.firstOrNull(),
        )
    }

    private fun breaches(samples: Collection<LinkSample>): List<String> {
        if (samples.isEmpty()) return listOf("network_unobserved")
        val out = mutableListOf<String>()
        if (samples.size >= config.sampleWindowSize && samples.all { (it.uplinkMbps ?: 0.0) < config.minUplinkMbps }) {
            out += "uplink_below_threshold"
        }
        if (samples.last().rttMs?.let { it > config.maxRttMs } == true) out += "rtt_above_threshold"
        if (samples.last().packetLossPercent?.let { it > config.maxPacketLossPercent } == true) {
            out += "packet_loss_above_threshold"
        }
        return out
    }

    private fun wifiAverageUplink(): Double = wifi.mapNotNull { it.uplinkMbps }.average().takeUnless { it.isNaN() } ?: 0.0
}
