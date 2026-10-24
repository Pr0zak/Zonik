package com.zonik.app.data.auth

import android.content.Context
import com.zonik.app.data.DebugLog
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.core.auth.AuthResult
import com.zonik.core.auth.ZonikAuthClient
import com.zonik.core.auth.describe
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.first
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Moves an install signed in with the legacy API key onto a device token of its own, silently,
 * once per app start: `POST /api/auth/devices` signed with the current key. On success the
 * token is saved and every request switches to `apiKey=<token>`; on any failure (a server older
 * than 0.48 answers 404, offline, …) the API key stays and the next launch tries again.
 */
@Singleton
class DeviceTokenUpgrader @Inject constructor(
    @ApplicationContext private val context: Context,
    private val settingsRepository: SettingsRepository,
    private val authClient: ZonikAuthClient,
) {

    suspend fun upgradeIfNeeded() {
        val config = settingsRepository.serverConfig.first() ?: return
        if (config.hasDeviceToken || config.apiKey.isBlank()) return
        val label = DeviceIdentity.label(context)
        val platform = DeviceIdentity.platform(context)
        when (val r = authClient.issueDeviceToken(config, label, platform)) {
            is AuthResult.Ok -> {
                // Re-read: the user may have signed out or switched server meanwhile.
                val now = settingsRepository.serverConfig.first()
                if (now == null || now.url != config.url || now.apiKey != config.apiKey || now.hasDeviceToken) {
                    DebugLog.w(TAG, "Config changed while upgrading; discarding the new token")
                    return
                }
                settingsRepository.saveServerConfig(now.copy(deviceToken = r.value.token))
                DebugLog.d(TAG, "Switched to a device token (\"$label\", $platform)")
            }
            is AuthResult.Http -> DebugLog.w(
                TAG,
                if (r.code == 404) "Server has no device tokens yet (404); keeping the API key"
                else "Device token upgrade refused (${r.code}: ${r.describe()}); keeping the API key"
            )
            is AuthResult.Failure -> DebugLog.w(TAG, "Device token upgrade failed (${r.describe()}); will retry next launch")
        }
    }

    private companion object {
        const val TAG = "DeviceToken"
    }
}
