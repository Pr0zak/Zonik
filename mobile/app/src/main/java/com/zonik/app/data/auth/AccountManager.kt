package com.zonik.app.data.auth

import com.zonik.app.data.DebugLog
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.core.auth.AuthResult
import com.zonik.core.auth.AuthUser
import com.zonik.core.auth.PairApproveResponse
import com.zonik.core.auth.PairInfo
import com.zonik.core.auth.ZonikAuthClient
import com.zonik.core.auth.describe
import com.zonik.core.model.ServerConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Signed-in account actions for Settings: who am I, sign out (revoking this device's token),
 * approve a TV's pairing code, mint a token for the paired watch.
 */
@Singleton
class AccountManager @Inject constructor(
    private val settingsRepository: SettingsRepository,
    private val authClient: ZonikAuthClient,
) {
    // Sign-out outlives the Settings screen: navigating to login clears its ViewModel.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    suspend fun config(): ServerConfig? = settingsRepository.serverConfig.first()

    /** The signed-in user, or a Http/Failure result (404 on servers without /api/auth). */
    suspend fun me(): AuthResult<AuthUser> {
        val config = config() ?: return AuthResult.Http(401, "Not signed in")
        return authClient.me(config)
    }

    /**
     * Clears the saved login (URL, user, key, token) right away, then — best effort — revokes
     * this device's token on the server, found as the `current: true` row of
     * `/api/auth/devices`.
     */
    fun signOut() {
        scope.launch {
            val config = config()
            withContext(NonCancellable) { settingsRepository.clearAll() }
            DebugLog.d(TAG, "Signed out")
            if (config == null || !config.hasDeviceToken) return@launch
            withTimeoutOrNull(REVOKE_TIMEOUT_MS) {
                val own = authClient.listDevices(config).valueOrNull()?.firstOrNull { it.current && it.kind != "session" }
                if (own == null) {
                    DebugLog.w(TAG, "Sign-out: couldn't find this device's token to revoke")
                    return@withTimeoutOrNull
                }
                when (val r = authClient.revokeDevice(config, own.id)) {
                    is AuthResult.Ok -> DebugLog.d(TAG, "Sign-out: revoked this device's token")
                    else -> DebugLog.w(TAG, "Sign-out: revoke failed (${r.describe()})")
                }
            } ?: DebugLog.w(TAG, "Sign-out: revoke timed out")
        }
    }

    suspend fun pairInfo(code: String): AuthResult<PairInfo> {
        val config = config() ?: return AuthResult.Http(401, "Not signed in")
        return authClient.pairInfo(config, code)
    }

    suspend fun approvePair(code: String): AuthResult<PairApproveResponse> {
        val config = config() ?: return AuthResult.Http(401, "Not signed in")
        return authClient.approvePair(config, code)
    }

    /** A device token of the watch's own; null when the server can't mint one (old server, offline). */
    suspend fun mintWatchToken(config: ServerConfig, watchName: String): String? =
        when (val r = authClient.issueDeviceToken(config, watchName, "wear")) {
            is AuthResult.Ok -> r.value.token
            else -> {
                DebugLog.w(TAG, "Watch token not minted (${r.describe()}); sending the phone's login")
                null
            }
        }

    private companion object {
        const val TAG = "Account"
        const val REVOKE_TIMEOUT_MS = 8_000L
    }
}
