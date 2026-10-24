package com.zonik.wear.ui.screens.pairing

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.zonik.core.auth.AuthResult
import com.zonik.core.auth.ServerUrlNormalizer
import com.zonik.core.auth.ZonikAuthClient
import com.zonik.wear.data.repository.WearSettingsRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Drives the watch's first-launch pairing flow:
 *   EnterUrl -> Pending(code) -> Paired (or Expired / Error)
 *
 * Reuses the server-side /api/pair endpoint already used by the TV app.
 */
class PairingViewModel(
    private val settings: WearSettingsRepository,
) : ViewModel() {

    private val authClient = ZonikAuthClient(clientName = "ZonikWear")

    private val _state = MutableStateFlow<PairingState>(PairingState.EnterUrl(""))
    val state: StateFlow<PairingState> = _state.asStateFlow()

    fun updateUrl(url: String) {
        val current = _state.value
        if (current is PairingState.EnterUrl) _state.value = current.copy(url = url)
    }

    fun requestCode() {
        val st = _state.value as? PairingState.EnterUrl ?: return
        val normalized = normalizeUrl(st.url)
        if (normalized.isBlank()) {
            _state.value = st.copy(error = "Enter a URL like http://zonik:3000")
            return
        }
        _state.value = PairingState.Requesting(normalized)
        viewModelScope.launch {
            try {
                when (val r = authClient.createPair(normalized, label = android.os.Build.MODEL, platform = "wear")) {
                    is AuthResult.Ok -> {
                        _state.value = PairingState.Pending(normalized, r.value.code)
                        pollUntilReady(normalized, r.value.code)
                    }
                    is AuthResult.Http -> _state.value = PairingState.EnterUrl(
                        url = st.url,
                        error = "Server responded ${r.code} — wrong URL?"
                    )
                    is AuthResult.Failure -> throw r.error
                }
            } catch (e: Exception) {
                Log.w(TAG, "Pair request failed: ${e.message}")
                _state.value = PairingState.EnterUrl(
                    url = st.url,
                    error = "Couldn't reach server: ${e.javaClass.simpleName}"
                )
            }
        }
    }

    fun cancelAndStartOver() {
        val st = _state.value
        val url = when (st) {
            is PairingState.Pending -> st.url.removePrefix("http://").removePrefix("https://")
            is PairingState.Requesting -> st.url.removePrefix("http://").removePrefix("https://")
            is PairingState.EnterUrl -> st.url
            else -> ""
        }
        _state.value = PairingState.EnterUrl(url)
    }

    private suspend fun pollUntilReady(serverUrl: String, code: String) {
        while (true) {
            delay(2_000)
            val st = _state.value
            if (st !is PairingState.Pending || st.code != code) return
            try {
                val payload = authClient.pollPair(serverUrl, code).valueOrNull() ?: continue
                run {
                    when (payload.status) {
                        "ready" -> {
                            // Pairing v2 servers add a device token for this watch; older ones
                            // send the account's API key. toServerConfig takes either.
                            val config = payload.toServerConfig(fallbackUrl = serverUrl)
                            if (config == null) {
                                _state.value = PairingState.EnterUrl(
                                    url = serverUrl,
                                    error = "Server returned ready but missing credentials"
                                )
                                return
                            }
                            settings.save(config)
                            _state.value = PairingState.Paired(config.url, config.username)
                            return
                        }
                        "expired" -> {
                            _state.value = PairingState.EnterUrl(
                                url = serverUrl,
                                error = "Code expired — try again"
                            )
                            return
                        }
                        else -> { /* still pending */ }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Poll failed: ${e.message}")
                // Keep polling — transient network blip.
            }
        }
    }

    // Same shorthand as the phone/TV: "zonik" → http://zonik.lan:3000, a bare host gets
    // http:// and :3000. (No last-octet shorthand here: the watch's own IP is not looked up.)
    private fun normalizeUrl(input: String): String = ServerUrlNormalizer.normalize(input).orEmpty()

    private companion object {
        const val TAG = "WearPairing"
    }
}

sealed class PairingState {
    data class EnterUrl(val url: String, val error: String? = null) : PairingState()
    data class Requesting(val url: String) : PairingState()
    data class Pending(val url: String, val code: String) : PairingState()
    data class Paired(val url: String, val username: String) : PairingState()
}
