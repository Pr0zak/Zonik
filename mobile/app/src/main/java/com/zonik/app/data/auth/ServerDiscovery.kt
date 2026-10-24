package com.zonik.app.data.auth

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import com.zonik.app.data.DebugLog
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.core.auth.AuthJson
import com.zonik.core.auth.AuthResult
import com.zonik.core.auth.DiscoveredServer
import com.zonik.core.auth.ServerUrlNormalizer
import com.zonik.core.auth.ZonikAuthClient
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.coroutines.resume

/**
 * Finds Zonik servers on the LAN, three ways at once:
 *  - mDNS / DNS-SD browse for `_zonik._tcp` (URL from the TXT `url`, else host:port),
 *  - a UDP `ZONIK?` broadcast to port 3000 (255.255.255.255 and the /24 broadcast),
 *  - probing well-known candidates (`http://zonik.lan:3000`, `http://zonik:3000`, the last-used
 *    server).
 * Every candidate is confirmed with `GET /api/auth/status` before it is shown. Results are
 * de-duplicated by the server's own advertised URL, so zonik.lan and its IP appear once.
 *
 * [discover] emits the growing list as servers answer and completes after [timeoutMs].
 */
@Singleton
class ServerDiscovery @Inject constructor(
    @ApplicationContext private val context: Context,
    private val authClient: ZonikAuthClient,
    private val settingsRepository: SettingsRepository,
) {

    fun discover(timeoutMs: Long = DEFAULT_TIMEOUT_MS): Flow<List<DiscoveredServer>> = channelFlow {
        val found = LinkedHashMap<String, DiscoveredServer>()
        val seenCandidates = HashSet<String>()
        val lock = Mutex()

        suspend fun consider(candidateUrl: String, source: DiscoveredServer.Source, hintName: String?) {
            val url = candidateUrl.trim().trimEnd('/')
            if (!lock.withLock { seenCandidates.add(url) }) return
            val status = authClient.status(url)
            if (status !is AuthResult.Ok) {
                DebugLog.d(TAG, "$source candidate $url not a Zonik server (${status.javaClass.simpleName})")
                return
            }
            val key = status.value.url?.trim()?.trimEnd('/')?.takeIf { it.isNotEmpty() } ?: url
            val server = DiscoveredServer(
                url = url,
                name = status.value.serverName ?: hintName,
                version = status.value.version,
                source = source,
            )
            val snapshot = lock.withLock {
                if (found.containsKey(key)) null
                else {
                    found[key] = server
                    found.values.toList()
                }
            } ?: return
            DebugLog.d(TAG, "Found ${server.title} at $url via $source")
            send(snapshot)
        }

        val multicastLock = acquireMulticastLock()
        try {
            withTimeoutOrNull(timeoutMs) {
                val jobs = listOf(
                    launch { browseMdns { url, name -> launch { consider(url, DiscoveredServer.Source.MDNS, name) } } },
                    launch(Dispatchers.IO) {
                        udpProbe(timeoutMs) { reply -> launch { consider(reply.url, DiscoveredServer.Source.UDP, reply.name) } }
                    },
                    launch {
                        val last = try { settingsRepository.lastServerUrl.first() } catch (_: Exception) { null }
                        (listOfNotNull(last) + PROBE_CANDIDATES).distinct().forEach { url ->
                            launch { consider(url, DiscoveredServer.Source.PROBE, null) }
                        }
                    },
                )
                jobs.forEach { it.join() }
            }
        } finally {
            multicastLock?.let { runCatching { it.release() } }
        }
        if (found.isEmpty()) send(emptyList())
    }

    // --- mDNS ---

    private suspend fun browseMdns(onFound: (url: String, name: String?) -> Unit) {
        val nsd = context.getSystemService(NsdManager::class.java) ?: return
        val services = Channel<NsdServiceInfo>(Channel.UNLIMITED)
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) { DebugLog.d(TAG, "mDNS browse started") }
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onServiceFound(serviceInfo: NsdServiceInfo) { services.trySend(serviceInfo) }
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                DebugLog.w(TAG, "mDNS browse failed: $errorCode")
                services.close()
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
        }
        try {
            nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            DebugLog.w(TAG, "mDNS browse unavailable: ${e.message}")
            return
        }
        try {
            // Older Android allows one resolve at a time, so resolve sequentially.
            for (info in services) {
                val resolved = resolve(nsd, info) ?: continue
                urlFrom(resolved)?.let { onFound(it, txt(resolved, "name") ?: resolved.serviceName) }
            }
        } finally {
            runCatching { nsd.stopServiceDiscovery(listener) }
        }
    }

    @Suppress("DEPRECATION") // resolveService: replaced on API 34 by registerServiceInfoCallback, still works
    private suspend fun resolve(nsd: NsdManager, info: NsdServiceInfo): NsdServiceInfo? =
        withTimeoutOrNull(RESOLVE_TIMEOUT_MS) {
            suspendCancellableCoroutine { cont ->
                try {
                    nsd.resolveService(info, object : NsdManager.ResolveListener {
                        override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                            DebugLog.w(TAG, "mDNS resolve of ${serviceInfo.serviceName} failed: $errorCode")
                            if (cont.isActive) cont.resume(null)
                        }
                        override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                            if (cont.isActive) cont.resume(serviceInfo)
                        }
                    })
                } catch (e: Exception) {
                    if (cont.isActive) cont.resume(null)
                }
            }
        }

    private fun txt(info: NsdServiceInfo, key: String): String? =
        info.attributes?.get(key)?.let { String(it, Charsets.UTF_8) }?.trim()?.takeIf { it.isNotEmpty() }

    @Suppress("DEPRECATION") // NsdServiceInfo.host: hostAddresses is API 34+
    private fun urlFrom(info: NsdServiceInfo): String? {
        txt(info, "url")?.takeIf { it.startsWith("http") }?.let { return it.trimEnd('/') }
        val host = info.host?.hostAddress ?: return null
        if (info.port <= 0) return null
        val scheme = txt(info, "scheme") ?: "http"
        val path = txt(info, "path")?.trimEnd('/').orEmpty()
        val hostPart = if (host.contains(':')) "[$host]" else host
        return "$scheme://$hostPart:${info.port}$path"
    }

    // --- UDP probe ---

    private fun udpProbe(timeoutMs: Long, onReply: (DiscoveredServer) -> Unit) {
        val deadline = System.currentTimeMillis() + timeoutMs
        try {
            DatagramSocket().use { socket ->
                socket.broadcast = true
                val payload = PROBE.toByteArray(Charsets.US_ASCII)
                val targets = listOfNotNull(
                    "255.255.255.255",
                    ServerUrlNormalizer.broadcastFor24(DeviceIdentity.lanIpv4(context)),
                ).distinct()
                for (t in targets) {
                    runCatching {
                        socket.send(DatagramPacket(payload, payload.size, InetAddress.getByName(t), UDP_PORT))
                    }.onFailure { DebugLog.d(TAG, "UDP probe to $t failed: ${it.message}") }
                }
                val buf = ByteArray(2048)
                while (true) {
                    val left = deadline - System.currentTimeMillis()
                    if (left <= 0) break
                    socket.soTimeout = left.toInt().coerceAtLeast(1)
                    val packet = DatagramPacket(buf, buf.size)
                    try {
                        socket.receive(packet)
                    } catch (_: SocketTimeoutException) {
                        break
                    }
                    val text = String(packet.data, packet.offset, packet.length, Charsets.UTF_8)
                    AuthJson.parseProbeReply(text)?.let(onReply)
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            DebugLog.d(TAG, "UDP probe unavailable: ${e.message}")
        }
    }

    private fun acquireMulticastLock(): WifiManager.MulticastLock? = try {
        val wifi = context.applicationContext.getSystemService(WifiManager::class.java)
        wifi?.createMulticastLock("zonik-discovery")?.apply {
            setReferenceCounted(false)
            acquire()
        }
    } catch (e: Exception) {
        DebugLog.w(TAG, "Multicast lock unavailable: ${e.message}")
        null
    }

    companion object {
        private const val TAG = "Discovery"
        const val DEFAULT_TIMEOUT_MS = 6_000L
        private const val RESOLVE_TIMEOUT_MS = 2_500L
        private const val SERVICE_TYPE = "_zonik._tcp"
        private const val PROBE = "ZONIK?"
        private const val UDP_PORT = 3000
        private val PROBE_CANDIDATES = listOf("http://zonik.lan:3000", "http://zonik:3000")
    }
}
