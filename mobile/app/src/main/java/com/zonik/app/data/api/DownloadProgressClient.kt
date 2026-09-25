package com.zonik.app.data.api

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import com.zonik.app.data.DebugLog
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.core.util.md5
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.max
import kotlin.math.min
import kotlin.random.Random

data class JobProgress(
    val jobId: String,
    val status: String = "pending",
    val progress: Long = 0L,
    val total: Long = 0L,
    val pct: Float = 0f,
    val message: String? = null,
    val error: String? = null,
    /** Library track to play once the job completes (new, or the copy already there). */
    val trackId: String? = null,
    val alreadyInLibrary: Boolean = false,
    /** Peers that failed this job — excluded when trying another source. */
    val failedSources: List<String> = emptyList(),
    /** Soulseek transfer state: requested/queued/connected/transferring/... */
    val transferState: String? = null,
    val speedBps: Long = 0L,
    val etaSeconds: Long? = null,
    val updatedAt: Long = System.currentTimeMillis()
)

@Singleton
class DownloadProgressClient @Inject constructor(
    private val settingsRepository: SettingsRepository,
    @ApplicationContext private val context: Context
) {

    companion object {
        private const val TAG = "DLProgressWS"
        private const val INITIAL_RECONNECT_MS = 1_500L
        private const val MAX_RECONNECT_MS = 30_000L
        // Stop hammering after this many consecutive failures with no good connect.
        private const val MAX_CONSECUTIVE_FAILURES = 6
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutex = Mutex()

    private val _progress = MutableStateFlow<Map<String, JobProgress>>(emptyMap())
    val progress: StateFlow<Map<String, JobProgress>> = _progress.asStateFlow()

    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()

    // True when there is real work to watch: either a non-terminal job in
    // [_progress], or the VM has told us the server reports active jobs.
    // The connect loop suspends on this and only spins up the WS when needed.
    private val hasActiveJobs = MutableStateFlow(false)
    // Set by the VM from its own server poll, OR'd with the _progress signal.
    @Volatile private var serverReportsActive = false
    // Flipped by the network callback so the loop can wake after host-unreachable.
    private val networkAvailable = MutableStateFlow(true)

    private var refcount = 0
    private var connectJob: Job? = null
    private var webSocket: WebSocket? = null
    private var reconnectMs = INITIAL_RECONNECT_MS
    private var consecutiveFailures = 0

    private val connectivityManager by lazy {
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    }
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private val client by lazy {
        OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)
            .connectTimeout(15, TimeUnit.SECONDS)
            .build()
    }

    /** Recompute whether the loop has genuine work to do. */
    private fun recomputeHasActiveJobs() {
        val anyNonTerminal = _progress.value.values.any { p ->
            p.status != "completed" && p.status != "failed" && p.status != "cancelled"
        }
        hasActiveJobs.value = anyNonTerminal || serverReportsActive
    }

    /**
     * Called by the ViewModel from its own server poll so the loop can run even
     * before any WS message has populated [_progress] (avoids a chicken-and-egg
     * where the loop won't connect until it has seen a job, but can only see a
     * job via the connection).
     */
    fun setServerReportsActive(active: Boolean) {
        serverReportsActive = active
        recomputeHasActiveJobs()
    }

    suspend fun acquire() {
        mutex.withLock {
            refcount++
            if (refcount == 1) {
                startConnectLoop()
            }
        }
    }

    suspend fun release() {
        mutex.withLock {
            refcount = max(0, refcount - 1)
            if (refcount == 0) {
                stopConnectLoop()
            }
        }
    }

    fun setJobStatus(jobId: String, status: String, message: String? = null) {
        _progress.update { current ->
            val existing = current[jobId] ?: JobProgress(jobId = jobId)
            current + (jobId to existing.copy(
                status = status,
                message = message ?: existing.message,
                updatedAt = System.currentTimeMillis()
            ))
        }
        recomputeHasActiveJobs()
    }

    /**
     * Fold a REST job snapshot into the progress map — the fallback when the
     * WebSocket is down or quiet, so rows still reach Done/Failed.
     */
    fun applyJobSnapshot(job: JobDetailResponse) {
        if (job.id.isBlank() || job.status.isBlank()) return
        _progress.update { current ->
            val existing = current[job.id] ?: JobProgress(jobId = job.id)
            current + (job.id to existing.copy(
                status = job.status,
                pct = if (job.status == "completed") 100f else existing.pct,
                error = job.error ?: existing.error,
                trackId = job.trackId ?: existing.trackId,
                alreadyInLibrary = job.alreadyInLibrary || existing.alreadyInLibrary,
                failedSources = job.failedSources.ifEmpty { existing.failedSources },
                updatedAt = System.currentTimeMillis()
            ))
        }
        recomputeHasActiveJobs()
    }

    /** Fold the REST transfer list (GET api/download/status) into the progress map. */
    fun applyTransfers(transfers: List<TransferInfo>) {
        val byJob = transfers.filter { !it.jobId.isNullOrBlank() }
            .groupBy { it.jobId!! }
            .mapValues { (_, ts) -> ts.firstOrNull { !isTerminalTransfer(it.state) } ?: ts.last() }
        if (byJob.isEmpty()) return
        _progress.update { current ->
            var next = current
            for ((jobId, t) in byJob) {
                next = next + (jobId to mergeTransfer(
                    current[jobId] ?: JobProgress(jobId = jobId),
                    t.state, t.receivedBytes, t.totalBytes, t.speed, t.etaSeconds?.toLong()
                ))
            }
            next
        }
        recomputeHasActiveJobs()
    }

    private fun isTerminalTransfer(state: String): Boolean =
        state.lowercase() in setOf("completed", "failed", "denied")

    private fun mergeTransfer(
        existing: JobProgress, state: String?, received: Long, total: Long, speed: Long, eta: Long?
    ): JobProgress {
        if (existing.status == "completed" || existing.status == "failed") return existing
        return existing.copy(
            status = if (existing.status.isBlank() || existing.status == "pending") "running" else existing.status,
            progress = received,
            total = if (total > 0) total else existing.total,
            pct = computePct(received, total, existing.pct),
            transferState = state?.takeIf { it.isNotBlank() }?.lowercase() ?: existing.transferState,
            speedBps = speed,
            etaSeconds = eta,
            updatedAt = System.currentTimeMillis()
        )
    }

    fun clearTerminal() {
        _progress.update { current ->
            current.filterValues { p ->
                p.status != "completed" && p.status != "failed" && p.status != "cancelled"
            }
        }
        recomputeHasActiveJobs()
    }

    /** Outcome of a single connect attempt, used to steer the backoff. */
    private enum class ConnectResult {
        /** Socket opened and later closed normally/transiently — resume quickly. */
        CLOSED,
        /** Host couldn't be resolved (off-network) — wait for connectivity. */
        HOST_UNREACHABLE,
        /** Some other failure — back off with the usual exponential delay. */
        FAILED
    }

    private fun startConnectLoop() {
        if (connectJob?.isActive == true) return
        registerNetworkCallback()
        connectJob = scope.launch {
            while (refcount > 0) {
                // 1. Suspend (don't spin) until there is genuine work to watch.
                //    `.first { it }` returns immediately if already true, else
                //    parks until the progress/server signal flips on.
                if (!hasActiveJobs.value) {
                    DebugLog.d(TAG, "No active jobs — idling until one appears")
                    _connected.value = false
                    hasActiveJobs.first { it }
                }
                if (refcount <= 0) break

                val config = settingsRepository.serverConfig.first()
                if (config == null) {
                    delay(2_000)
                    continue
                }

                // Re-sync our offline flag with the real OS state before each
                // attempt so a stale `false` (set on a prior host-unreachable)
                // can't trap the loop when connectivity is actually present.
                if (!networkAvailable.value && connectivityManager.activeNetwork != null) {
                    networkAvailable.value = true
                }

                val result = try {
                    connectOnce(config.url, config.username, config.apiKey)
                } catch (e: Exception) {
                    DebugLog.e(TAG, "Connect loop error: ${e.message}")
                    if (e is UnknownHostException) ConnectResult.HOST_UNREACHABLE else ConnectResult.FAILED
                }
                if (refcount <= 0) break

                when (result) {
                    ConnectResult.CLOSED -> {
                        // A clean/transient close: a real connection happened,
                        // so reset the failure budget and resume promptly.
                        consecutiveFailures = 0
                        reconnectMs = INITIAL_RECONNECT_MS
                        delay(INITIAL_RECONNECT_MS)
                    }
                    ConnectResult.HOST_UNREACHABLE -> {
                        consecutiveFailures++
                        val hasNetwork = connectivityManager.activeNetwork != null
                        if (!hasNetwork) {
                            // Genuinely offline (no network at all): park until the
                            // OS reports a network again, or the active-job signal
                            // clears. onAvailable WILL fire when connectivity returns.
                            DebugLog.d(TAG, "Host unreachable, no network — parking until connectivity returns")
                            networkAvailable.value = false
                            awaitResumeSignal()
                            consecutiveFailures = 0
                            reconnectMs = INITIAL_RECONNECT_MS
                        } else {
                            // Network is up but the server name won't resolve (server
                            // down / off the VPN/Tailscale link). onAvailable won't
                            // fire again, so we can't park on it — back off with jitter
                            // (capped) and keep slow-retrying while work is active. The
                            // ceiling adds a longer cooldown so this stays a slow retry,
                            // never the 30s-forever storm (the top-of-loop hasActiveJobs
                            // gate idles us as soon as the download actually finishes).
                            networkAvailable.value = true
                            if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                                DebugLog.d(TAG, "Host unreachable x$consecutiveFailures with network up — cooling down")
                                delay(MAX_RECONNECT_MS)
                                consecutiveFailures = 0
                                reconnectMs = INITIAL_RECONNECT_MS
                            } else {
                                reconnectMs = min(reconnectMs * 2, MAX_RECONNECT_MS)
                                val jitter = if (reconnectMs > 0) Random.nextLong(0, reconnectMs / 2 + 1) else 0L
                                delay(reconnectMs + jitter)
                            }
                        }
                    }
                    ConnectResult.FAILED -> {
                        consecutiveFailures++
                        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                            DebugLog.d(TAG, "Hit $consecutiveFailures consecutive failures — pausing until network or new job")
                            reconnectMs = INITIAL_RECONNECT_MS
                            // Stop the storm. Cool down, then re-seed connectivity
                            // from the real OS state and park until network is
                            // (re)available or the active-job signal clears.
                            delay(MAX_RECONNECT_MS)
                            networkAvailable.value = connectivityManager.activeNetwork != null
                            awaitResumeSignal()
                            consecutiveFailures = 0
                        } else {
                            reconnectMs = min(reconnectMs * 2, MAX_RECONNECT_MS)
                            val jitter = if (reconnectMs > 0) Random.nextLong(0, reconnectMs / 2 + 1) else 0L
                            delay(reconnectMs + jitter)
                        }
                    }
                }
            }
            _connected.value = false
        }
    }

    private fun stopConnectLoop() {
        connectJob?.cancel()
        connectJob = null
        unregisterNetworkCallback()
        webSocket?.close(1000, "client released")
        webSocket = null
        _connected.value = false
        reconnectMs = INITIAL_RECONNECT_MS
        consecutiveFailures = 0
    }

    private fun registerNetworkCallback() {
        if (networkCallback != null) return
        try {
            val cb = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    DebugLog.d(TAG, "Network available — unparking connect loop")
                    networkAvailable.value = true
                }
            }
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build()
            connectivityManager.registerNetworkCallback(request, cb)
            networkCallback = cb
            // Seed current state so a loop started while online doesn't park.
            networkAvailable.value = connectivityManager.activeNetwork != null
        } catch (e: Exception) {
            DebugLog.e(TAG, "registerNetworkCallback failed: ${e.message}")
            // If we can't observe connectivity, don't trap the loop offline.
            networkAvailable.value = true
        }
    }

    private fun unregisterNetworkCallback() {
        networkCallback?.let {
            try {
                connectivityManager.unregisterNetworkCallback(it)
            } catch (e: Exception) {
                DebugLog.e(TAG, "unregisterNetworkCallback failed: ${e.message}")
            }
        }
        networkCallback = null
    }

    /**
     * Park the loop until it makes sense to stop waiting: the OS reports a
     * network is available again, OR there's no longer any active work (in
     * which case the outer loop will simply go back to idling on
     * [hasActiveJobs]). Either way, a host-unreachable storm can't keep
     * grinding reconnect attempts off-network.
     */
    private suspend fun awaitResumeSignal() {
        combine(networkAvailable, hasActiveJobs) { net, active -> net || !active }
            .first { it }
    }

    private suspend fun connectOnce(serverUrl: String, username: String, apiKey: String): ConnectResult {
        val wsUrl = buildWsUrl(serverUrl, username, apiKey)
        val request = Request.Builder().url(wsUrl).build()
        val opened = CompletableDeferred<Unit>()
        // Completed with the outcome of this socket's lifetime.
        val finished = CompletableDeferred<ConnectResult>()

        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                DebugLog.d(TAG, "WS opened ${response.code}")
                _connected.value = true
                reconnectMs = INITIAL_RECONNECT_MS
                consecutiveFailures = 0
                if (!opened.isCompleted) opened.complete(Unit)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                DebugLog.d(TAG, "WS closing $code $reason")
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                DebugLog.d(TAG, "WS closed $code $reason")
                _connected.value = false
                if (!finished.isCompleted) finished.complete(ConnectResult.CLOSED)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                DebugLog.e(TAG, "WS failure ${t.message} (code=${response?.code})")
                val hadOpened = opened.isCompleted
                _connected.value = false
                val result = if (t is UnknownHostException || t.cause is UnknownHostException) {
                    ConnectResult.HOST_UNREACHABLE
                } else if (hadOpened) {
                    // Failed after a successful open — treat as a transient close.
                    ConnectResult.CLOSED
                } else {
                    ConnectResult.FAILED
                }
                if (!finished.isCompleted) finished.complete(result)
            }
        }

        webSocket = client.newWebSocket(request, listener)
        return try {
            finished.await()
        } finally {
            webSocket?.cancel()
            webSocket = null
            _connected.value = false
        }
    }

    private fun buildWsUrl(serverUrl: String, username: String, apiKey: String): String {
        val base = serverUrl.trimEnd('/')
        val wsBase = when {
            base.startsWith("https://") -> "wss://" + base.removePrefix("https://")
            base.startsWith("http://") -> "ws://" + base.removePrefix("http://")
            else -> "ws://$base"
        }
        val salt = (1..16).map { "abcdefghijklmnopqrstuvwxyz0123456789".random() }.joinToString("")
        val token = md5("$apiKey$salt")
        return "$wsBase/api/ws?u=$username&t=$token&s=$salt&v=1.16.1&c=ZonikApp&f=json"
    }

    private fun handleMessage(text: String) {
        try {
            val obj = JSONObject(text)
            val type = obj.optString("type", "")
            when (type) {
                "job_update" -> handleJobUpdate(obj)
                "transfer_progress" -> handleTransferProgress(obj)
                else -> { /* ignore */ }
            }
        } catch (e: Exception) {
            DebugLog.e(TAG, "Parse error: ${e.message}")
        }
    }

    // Server shape: {"type":"job_update","job":{id,status,progress,total,description,
    // track_id?, already_in_library?, error?}} — see backend/api/websocket.py.
    private fun handleJobUpdate(obj: JSONObject) {
        val data = obj.optJSONObject("job") ?: obj.optJSONObject("data") ?: obj
        val jobId = data.optString("id", data.optString("job_id", ""))
        if (jobId.isBlank()) return
        val status = data.optString("status", "")
        val progress = data.optLong("progress", 0L)
        val total = data.optLong("total", 0L)
        val message = data.optString("description").takeIf { it.isNotBlank() }
            ?: data.optString("message").takeIf { it.isNotBlank() }
        val error = data.optString("error").takeIf { it.isNotBlank() }
        val trackId = data.optString("track_id").takeIf { it.isNotBlank() && it != "null" }
        val already = data.optBoolean("already_in_library", false)
        val failedSources = data.optJSONArray("failed_sources")?.let { arr ->
            (0 until arr.length()).mapNotNull { arr.optString(it).takeIf { u -> u.isNotBlank() } }
        } ?: emptyList()
        _progress.update { current ->
            val existing = current[jobId] ?: JobProgress(jobId = jobId)
            // Job progress is a 0/1 step count except while bytes are mirrored
            // onto it; only trust it once the job is finished.
            val terminal = status == "completed" || status == "failed"
            current + (jobId to existing.copy(
                status = if (status.isNotBlank()) status else existing.status,
                pct = if (status == "completed") 100f else existing.pct,
                progress = if (terminal && total > 1) progress else existing.progress,
                total = if (terminal && total > 1) total else existing.total,
                message = message ?: existing.message,
                error = error ?: existing.error,
                trackId = trackId ?: existing.trackId,
                alreadyInLibrary = already || existing.alreadyInLibrary,
                failedSources = failedSources.ifEmpty { existing.failedSources },
                updatedAt = System.currentTimeMillis()
            ))
        }
        recomputeHasActiveJobs()
    }

    // Server shape: {"type":"transfer_progress","transfers":[{job_id, state,
    // received_bytes, total_bytes, speed, eta_seconds, error, ...}]} — the full
    // transfer list every time.
    private fun handleTransferProgress(obj: JSONObject) {
        val transfers = obj.optJSONArray("transfers") ?: return
        val byJob = mutableMapOf<String, JSONObject>()
        for (i in 0 until transfers.length()) {
            val t = transfers.optJSONObject(i) ?: continue
            val jobId = t.optString("job_id").takeIf { it.isNotBlank() && it != "null" } ?: continue
            // A job that fell back to another source has several transfers;
            // the live one wins over the one that already failed.
            if (byJob[jobId]?.optString("state")?.let { !isTerminalTransfer(it) } == true &&
                isTerminalTransfer(t.optString("state"))) continue
            byJob[jobId] = t
        }
        if (byJob.isEmpty()) return
        _progress.update { current ->
            var next = current
            for ((jobId, t) in byJob) {
                next = next + (jobId to mergeTransfer(
                    current[jobId] ?: JobProgress(jobId = jobId),
                    t.optString("state"),
                    t.optLong("received_bytes", 0L),
                    t.optLong("total_bytes", 0L),
                    t.optLong("speed", 0L),
                    if (t.isNull("eta_seconds")) null else t.optLong("eta_seconds")
                ))
            }
            next
        }
        recomputeHasActiveJobs()
    }

    private fun computePct(progress: Long, total: Long, fallback: Float): Float {
        if (total <= 0L) return fallback
        val raw = (progress.toFloat() / total.toFloat()) * 100f
        return raw.coerceIn(0f, 100f)
    }
}
