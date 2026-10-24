package com.zonik.app.ui.screens.login

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.zonik.app.data.DebugLog
import com.zonik.app.data.auth.DeviceIdentity
import com.zonik.app.data.auth.ServerDiscovery
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.core.auth.AuthResult
import com.zonik.core.auth.DiscoveredServer
import com.zonik.core.auth.ServerUrlNormalizer
import com.zonik.core.auth.SubsonicAuth
import com.zonik.core.auth.ZonikAuthClient
import com.zonik.core.auth.describe
import com.zonik.core.model.PingResponse
import com.zonik.core.model.ServerConfig
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import javax.inject.Inject

enum class LoginStep {
    /** Choose a discovered server or type one. */
    PickServer,
    /** Phone (and TV fallback): username + password, or the legacy username + API key. */
    Credentials,
    /** Show a pairing code + QR and wait for a signed-in user to approve it. */
    Pairing,
}

data class PairingUi(
    val server: DiscoveredServer,
    val code: String? = null,
    /** Local clock time the code stops working. */
    val expiresAtMs: Long = 0L,
    val error: String? = null,
) {
    /** What the QR encodes: the server's approval page for this code. */
    val approveUrl: String? get() = code?.let { "${server.url.trimEnd('/')}/pair?code=$it" }
}

data class LoginUiState(
    val step: LoginStep = LoginStep.PickServer,
    val discovering: Boolean = true,
    val servers: List<DiscoveredServer> = emptyList(),
    val selected: DiscoveredServer? = null,
    /** Selected server answered 404 on /api/auth/status: older than 0.44, API key only. */
    val legacyServer: Boolean = false,
    /** TV: the manual address field is shown (hidden by default). Phone: always shown. */
    val manualEntry: Boolean = false,
    val manualUrl: String = "",
    val manualError: String? = null,
    val checkingManual: Boolean = false,
    val username: String = "",
    val password: String = "",
    val apiKey: String = "",
    val useApiKey: Boolean = false,
    val isLoading: Boolean = false,
    val error: String? = null,
    val pairing: PairingUi? = null,
    val isSuccess: Boolean = false,
)

@HiltViewModel
class LoginViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val settingsRepository: SettingsRepository,
    private val authClient: ZonikAuthClient,
    private val discovery: ServerDiscovery,
) : ViewModel() {

    val isTv: Boolean = DeviceIdentity.isTv(context)

    private val _uiState = MutableStateFlow(LoginUiState())
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    private var discoveryJob: Job? = null
    private var pairingJob: Job? = null
    private var autoPicked = false

    private val pingClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()
    private val json = Json { ignoreUnknownKeys = true }

    init {
        startDiscovery()
    }

    // --- discovery / server choice ---

    fun startDiscovery() {
        discoveryJob?.cancel()
        _uiState.update { it.copy(discovering = true, servers = emptyList()) }
        val startedAt = System.currentTimeMillis()
        discoveryJob = viewModelScope.launch {
            // TV: with exactly one server, go straight to pairing — after ~3 s so a second
            // server still has a chance to answer, or as soon as the search ends.
            val timer = if (isTv) launch {
                delay(AUTO_PICK_AFTER_MS)
                maybeAutoPick()
            } else null
            discovery.discover().collect { list ->
                _uiState.update { it.copy(servers = list) }
                if (System.currentTimeMillis() - startedAt >= AUTO_PICK_AFTER_MS) maybeAutoPick()
            }
            timer?.cancel()
            _uiState.update { it.copy(discovering = false) }
            DebugLog.d(TAG, "Discovery done: ${_uiState.value.servers.size} server(s)")
            maybeAutoPick()
        }
    }

    private fun maybeAutoPick() {
        if (!isTv || autoPicked) return
        val s = _uiState.value
        if (s.step != LoginStep.PickServer || s.manualEntry) return
        val only = s.servers.singleOrNull() ?: return
        autoPicked = true
        selectServer(only)
    }

    fun selectServer(server: DiscoveredServer, legacy: Boolean = false) {
        autoPicked = true
        _uiState.update {
            it.copy(
                selected = server,
                legacyServer = legacy,
                useApiKey = legacy,
                error = null,
                manualError = null,
            )
        }
        if (isTv) startPairing(server)
        else _uiState.update { it.copy(step = LoginStep.Credentials) }
    }

    fun backToServers() {
        stopPairing()
        _uiState.update {
            it.copy(step = LoginStep.PickServer, error = null, isLoading = false, pairing = null)
        }
        if (_uiState.value.servers.isEmpty() && !_uiState.value.discovering) startDiscovery()
    }

    fun showManualEntry(show: Boolean) {
        if (show) stopPairing()
        _uiState.update {
            it.copy(
                manualEntry = show,
                manualError = null,
                step = if (show) LoginStep.PickServer else it.step,
                pairing = if (show) null else it.pairing,
            )
        }
    }

    fun updateManualUrl(url: String) = _uiState.update { it.copy(manualUrl = url, manualError = null) }

    /** Normalizes the typed address, confirms it is a Zonik server, then selects it. */
    fun submitManualUrl() {
        val typed = _uiState.value.manualUrl
        val url = ServerUrlNormalizer.normalize(typed, DeviceIdentity.lanIpv4(context))
        if (url == null) {
            _uiState.update {
                it.copy(manualError = "Enter an address like zonik, .205, 10.0.0.205 or https://music.example.com")
            }
            return
        }
        _uiState.update { it.copy(checkingManual = true, manualError = null) }
        viewModelScope.launch {
            val r = authClient.status(url)
            _uiState.update { it.copy(checkingManual = false) }
            when {
                r is AuthResult.Ok -> selectServer(
                    DiscoveredServer(url, r.value.serverName, r.value.version, DiscoveredServer.Source.MANUAL)
                )
                // No /api/auth on servers older than 0.44: still usable with an API key (phone)
                // or the legacy pairing flow (TV).
                r is AuthResult.Http && r.code == 404 -> {
                    DebugLog.d(TAG, "$url has no /api/auth/status; treating as a legacy server")
                    selectServer(DiscoveredServer(url, null, null, DiscoveredServer.Source.MANUAL), legacy = true)
                }
                else -> _uiState.update { it.copy(manualError = "Can't use $url: ${r.describe()}") }
            }
        }
    }

    // --- credentials (phone) ---

    fun updateUsername(username: String) = _uiState.update { it.copy(username = username, error = null) }
    fun updatePassword(password: String) = _uiState.update { it.copy(password = password, error = null) }
    fun updateApiKey(apiKey: String) = _uiState.update { it.copy(apiKey = apiKey, error = null) }
    fun setUseApiKey(use: Boolean) = _uiState.update { it.copy(useApiKey = use, error = null) }

    /** TV fallback from manual entry: type a username + password instead of pairing. */
    fun useCredentialsInstead() {
        val server = _uiState.value.selected ?: return
        stopPairing()
        _uiState.update { it.copy(step = LoginStep.Credentials, pairing = null, selected = server) }
    }

    fun signIn() {
        val state = _uiState.value
        val server = state.selected ?: return
        if (state.username.isBlank()) {
            _uiState.update { it.copy(error = "Enter your username") }
            return
        }
        if (state.useApiKey) {
            if (state.apiKey.isBlank()) {
                _uiState.update { it.copy(error = "Enter your API key") }
                return
            }
            loginWithApiKey(server.url, state.username.trim(), state.apiKey.trim())
        } else {
            if (state.password.isEmpty()) {
                _uiState.update { it.copy(error = "Enter your password") }
                return
            }
            loginWithPassword(server.url, state.username.trim(), state.password)
        }
    }

    private fun loginWithPassword(url: String, username: String, password: String) {
        _uiState.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val r = authClient.deviceLogin(
                url, username, password,
                label = DeviceIdentity.label(context),
                platform = DeviceIdentity.platform(context),
            )
            when (r) {
                is AuthResult.Ok -> {
                    val config = ServerConfig(
                        url = url,
                        username = r.value.user.username,
                        apiKey = "",
                        deviceToken = r.value.token,
                    )
                    settingsRepository.saveServerConfig(config)
                    DebugLog.d(TAG, "Signed in to $url as ${config.username} with a device token")
                    _uiState.update { it.copy(isLoading = false, isSuccess = true, password = "") }
                }
                is AuthResult.Http -> {
                    DebugLog.w(TAG, "Password sign-in refused: ${r.code}")
                    val message = when (r.code) {
                        401 -> "Invalid username or password"
                        403 -> r.message ?: "Account disabled"
                        429 -> r.message ?: "Too many attempts, try again later"
                        404 -> null
                        else -> r.describe()
                    }
                    if (r.code == 404) {
                        // Server predates password sign-in for apps: switch to the API key form.
                        _uiState.update {
                            it.copy(
                                isLoading = false, useApiKey = true, legacyServer = true,
                                error = "This server doesn't support password sign-in yet. Use your API key."
                            )
                        }
                    } else {
                        _uiState.update { it.copy(isLoading = false, error = message) }
                    }
                }
                is AuthResult.Failure -> {
                    DebugLog.e(TAG, "Password sign-in failed", r.error)
                    _uiState.update { it.copy(isLoading = false, error = r.describe()) }
                }
            }
        }
    }

    private fun loginWithApiKey(url: String, username: String, apiKey: String) {
        _uiState.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val config = ServerConfig(url = url, username = username, apiKey = apiKey)
            val problem = testConnection(config)
            if (problem != null) {
                _uiState.update { it.copy(isLoading = false, error = problem) }
                return@launch
            }
            settingsRepository.saveServerConfig(config)
            DebugLog.d(TAG, "Signed in to $url with an API key")
            _uiState.update { it.copy(isLoading = false, isSuccess = true) }
        }
    }

    // --- pairing (TV, and "Pair with a code" on the phone) ---

    fun startPairing(server: DiscoveredServer? = _uiState.value.selected) {
        server ?: return
        pairingJob?.cancel()
        _uiState.update {
            it.copy(step = LoginStep.Pairing, selected = server, pairing = PairingUi(server), manualEntry = false)
        }
        val label = DeviceIdentity.label(context)
        val platform = DeviceIdentity.platform(context)
        pairingJob = viewModelScope.launch {
            while (isActive) {
                val created = authClient.createPair(server.url, label, platform)
                if (created !is AuthResult.Ok) {
                    DebugLog.w(TAG, "Pairing code request failed: ${created.describe()}")
                    _uiState.update {
                        it.copy(pairing = PairingUi(server, error = "Couldn't get a pairing code: ${created.describe()}"))
                    }
                    delay(RETRY_MS)
                    continue
                }
                val code = created.value.code
                val expiresAt = expiryFrom(created.value.expires)
                DebugLog.d(TAG, "Pairing code issued (expires in ${(expiresAt - System.currentTimeMillis()) / 1000}s)")
                _uiState.update { it.copy(pairing = PairingUi(server, code, expiresAt)) }

                while (isActive) {
                    delay(POLL_MS)
                    if (System.currentTimeMillis() >= expiresAt) break // renew
                    val poll = authClient.pollPair(server.url, code).valueOrNull() ?: continue
                    if (poll.isExpired) break
                    if (!poll.isReady) continue
                    val config = poll.toServerConfig(fallbackUrl = server.url)
                    if (config == null) {
                        DebugLog.w(TAG, "Pairing reply was ready but incomplete")
                        _uiState.update {
                            it.copy(pairing = it.pairing?.copy(error = "The server's reply was incomplete; getting a new code"))
                        }
                        break
                    }
                    if (finishPairing(config, server.url, poll.displayName)) return@launch
                    break
                }
            }
        }
    }

    /** Saves the paired config once it is shown to work; false (and an error shown) otherwise. */
    private suspend fun finishPairing(config: ServerConfig, polledUrl: String, displayName: String?): Boolean {
        // The reply carries the server's advertised URL; fall back to the one we reached it at.
        val candidates = listOf(config, config.copy(url = polledUrl.trimEnd('/'))).distinctBy { it.url }
        var lastProblem: String? = null
        for (c in candidates) {
            val problem = testConnection(c)
            if (problem == null) {
                settingsRepository.saveServerConfig(c)
                DebugLog.d(
                    TAG,
                    "Paired with ${c.url} as ${displayName ?: c.username} " +
                        "(${if (c.hasDeviceToken) "device token" else "API key"})"
                )
                _uiState.update { it.copy(isSuccess = true) }
                pairingJob = null
                return true
            }
            lastProblem = problem
        }
        _uiState.update {
            it.copy(pairing = it.pairing?.copy(error = "Paired, but the server didn't accept the login ($lastProblem). Try again."))
        }
        return false
    }

    fun renewCode() = startPairing(_uiState.value.selected)

    fun stopPairing() {
        pairingJob?.cancel()
        pairingJob = null
    }

    private fun expiryFrom(iso: String?): Long {
        val now = System.currentTimeMillis()
        val fallback = now + CODE_LIFETIME_MS
        val parsed = try {
            iso?.let { java.time.Instant.parse(it).toEpochMilli() }
        } catch (_: Exception) {
            null
        } ?: return fallback
        // Trust the server's expiry only when the clocks roughly agree.
        val left = parsed - now
        return if (left in 10_000L..(CODE_LIFETIME_MS + 60_000L)) parsed else fallback
    }

    // --- connection test ---

    private suspend fun testConnection(config: ServerConfig): String? = withContext(Dispatchers.IO) {
        try {
            val url = SubsonicAuth.appendTo("${config.url.trimEnd('/')}/rest/ping.view", config, "ZonikApp", json = true)
            DebugLog.d(TAG, "Testing connection to ${config.url}")
            pingClient.newCall(Request.Builder().url(url).build()).execute().use { response ->
                if (!response.isSuccessful) return@withContext "Server returned ${response.code}"
                val body = response.body?.string() ?: return@withContext "Empty response from server"
                val ping = json.decodeFromString<PingResponse>(body)
                if (!ping.response.isOk) {
                    val error = ping.response.error
                    DebugLog.e(TAG, "Auth failed: ${error?.message}")
                    return@withContext error?.message ?: "Authentication failed"
                }
                null
            }
        } catch (e: java.net.UnknownHostException) {
            "Server not found. Check the address."
        } catch (e: java.net.ConnectException) {
            "Cannot connect to server. Check the address and port."
        } catch (e: java.net.SocketTimeoutException) {
            "Connection timed out. Server may be offline."
        } catch (e: Exception) {
            DebugLog.e(TAG, "Connection test failed", e)
            "Connection failed: ${e.message}"
        }
    }

    override fun onCleared() {
        stopPairing()
        discoveryJob?.cancel()
    }

    private companion object {
        const val TAG = "Login"
        const val AUTO_PICK_AFTER_MS = 3_000L
        const val POLL_MS = 2_000L
        const val RETRY_MS = 5_000L
        const val CODE_LIFETIME_MS = 300_000L
    }
}
