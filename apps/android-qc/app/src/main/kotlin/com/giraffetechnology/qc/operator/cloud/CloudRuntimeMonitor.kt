package com.giraffetechnology.qc.operator.cloud

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.provider.Settings
import com.giraffetechnology.qc.sku.MnnRuntime
import com.giraffetechnology.qc.sku.MnnRuntimeState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume

/** Cloud-aware readiness adapter; implements the historical seam until it is renamed repo-wide. */
class CloudRuntimeMonitor(
    context: Context,
    private val client: OperatorCloudClient,
    val networkPolicy: NetworkPolicy,
    private val pendingReconciler: CloudPendingJobReconciler? = null,
    private val pollMs: Long = 5_000,
) : MnnRuntime {
    private val appContext = context.applicationContext
    private val connectivity = appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _runtimeState = MutableStateFlow<MnnRuntimeState>(MnnRuntimeState.Loading)
    override val runtimeState: StateFlow<MnnRuntimeState> = _runtimeState.asStateFlow()
    override val inferenceVerified: Boolean get() = _runtimeState.value is MnnRuntimeState.Ready
    private var job: Job? = null
    private var boundNetwork: OperatorNetwork = OperatorNetwork.NONE
    private var callback: ConnectivityManager.NetworkCallback? = null

    @Volatile var cloudReachable: Boolean = false
        private set
    @Volatile var lastDecision: NetworkDecision = NetworkDecision(OperatorNetwork.NONE, listOf("network_unobserved"), false)
        private set

    val padDeviceId: String = Settings.Secure.getString(appContext.contentResolver, Settings.Secure.ANDROID_ID)
        ?.let { "pad_$it" } ?: "pad_unprovisioned"

    fun start() {
        if (job != null) return
        job = scope.launch {
            while (isActive) {
                refresh()
                delay(pollMs)
            }
        }
    }

    suspend fun refresh() {
        val samples = coroutineScope {
            listOf(
                async { sampleTransport(NetworkCapabilities.TRANSPORT_WIFI, OperatorNetwork.WIFI) },
                async { sampleTransport(NetworkCapabilities.TRANSPORT_CELLULAR, OperatorNetwork.CELLULAR) },
            ).awaitAll().filterNotNull()
        }
        samples.forEach { sample ->
            lastDecision = networkPolicy.observe(sample)
        }
        applySelection(lastDecision.selected)
        cloudReachable = runCatching { client.health() }.getOrDefault(false)
        if (cloudReachable && networkPolicy.currentNetwork() != OperatorNetwork.NONE) {
            runCatching { pendingReconciler?.runDue() }
        }
        _runtimeState.value = if (
            cloudReachable && networkPolicy.currentNetwork() != OperatorNetwork.NONE
        ) MnnRuntimeState.Ready else MnnRuntimeState.NotReady
    }

    private suspend fun sampleTransport(transport: Int, type: OperatorNetwork): LinkSample? =
        withTimeoutOrNull(4_000) {
            suspendCancellableCoroutine { continuation ->
                val completed = AtomicBoolean(false)
                lateinit var cb: ConnectivityManager.NetworkCallback
                fun finish(sample: LinkSample?) {
                    if (!completed.compareAndSet(false, true)) return
                    runCatching { connectivity.unregisterNetworkCallback(cb) }
                    if (continuation.isActive) continuation.resume(sample)
                }
                cb = object : ConnectivityManager.NetworkCallback() {
                    override fun onAvailable(network: android.net.Network) {
                        scope.launch {
                            val caps = connectivity.getNetworkCapabilities(network)
                            val probe = runCatching { client.probe(network) }.getOrNull()
                            finish(
                                LinkSample(
                                    network = type,
                                    uplinkMbps = probe?.uplinkMbps
                                        ?: caps?.linkUpstreamBandwidthKbps?.takeIf { it > 0 }?.div(1000.0),
                                    rttMs = probe?.rttMs,
                                    packetLossPercent = probe?.packetLossPercent ?: 100.0,
                                    observedAtMs = System.currentTimeMillis(),
                                )
                            )
                        }
                    }

                    override fun onUnavailable() = finish(null)
                }
                continuation.invokeOnCancellation {
                    if (completed.compareAndSet(false, true)) {
                        runCatching { connectivity.unregisterNetworkCallback(cb) }
                    }
                }
                connectivity.requestNetwork(
                    NetworkRequest.Builder()
                        .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                        .addTransportType(transport)
                        .build(),
                    cb,
                    3_500,
                )
            }
        }

    private fun applySelection(selected: OperatorNetwork) {
        if (networkPolicy.activeJobNetwork() != null || selected == boundNetwork) return
        callback?.let { runCatching { connectivity.unregisterNetworkCallback(it) } }
        callback = null
        if (selected == OperatorNetwork.NONE) {
            connectivity.bindProcessToNetwork(null)
            boundNetwork = OperatorNetwork.NONE
            return
        }
        val transport = if (selected == OperatorNetwork.WIFI) {
            NetworkCapabilities.TRANSPORT_WIFI
        } else NetworkCapabilities.TRANSPORT_CELLULAR
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: android.net.Network) {
                if (networkPolicy.activeJobNetwork() == null && networkPolicy.currentNetwork() == selected) {
                    connectivity.bindProcessToNetwork(network)
                    boundNetwork = selected
                }
            }
        }
        callback = cb
        connectivity.requestNetwork(
            NetworkRequest.Builder().addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .addTransportType(transport).build(),
            cb,
        )
    }
}
