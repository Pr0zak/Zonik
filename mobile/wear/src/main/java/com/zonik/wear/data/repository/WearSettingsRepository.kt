package com.zonik.wear.data.repository

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.zonik.core.model.ServerConfig
import com.zonik.core.security.CredentialCipher
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "wear_settings")

/**
 * Wear-side persistence for the ServerConfig (url + username + apiKey + deviceToken).
 * Kept independent from :app's SettingsRepository — different process,
 * different DataStore file, simpler key set.
 */
class WearSettingsRepository(context: Context) {

    private val store = context.dataStore

    // The API key and the device token are stored encrypted (see CredentialCipher). current()
    // runs on every network request, so the plain text is kept alongside the stored value it
    // came from rather than decrypted through the Keystore each time.
    private val revealed = java.util.concurrent.ConcurrentHashMap<String, String>()

    private fun reveal(stored: String?): String? {
        if (stored == null) return null
        revealed[stored]?.let { return it }
        val plain = CredentialCipher.decrypt(stored) ?: return null
        if (revealed.size > 8) revealed.clear()
        revealed[stored] = plain
        return plain
    }

    val serverConfig: Flow<ServerConfig?> = store.data.map { prefs ->
        val url = prefs[SERVER_URL] ?: return@map null
        val username = prefs[USERNAME] ?: return@map null
        // Null when a credential can no longer be decrypted (a restore onto another watch):
        // the watch then shows pairing again rather than failing every request.
        val apiKey = reveal(prefs[API_KEY]) ?: return@map null
        val token = prefs[DEVICE_TOKEN]?.let { reveal(it) ?: return@map null }?.takeIf { it.isNotBlank() }
        ServerConfig(url, username, apiKey, token).takeIf { it.hasCredentials }
    }

    suspend fun current(): ServerConfig? = serverConfig.first()

    suspend fun save(config: ServerConfig) {
        store.edit { prefs ->
            prefs[SERVER_URL] = config.url
            prefs[USERNAME] = config.username
            prefs[API_KEY] = CredentialCipher.encrypt(config.apiKey)
            val token = config.deviceToken?.takeIf { it.isNotBlank() }
            if (token != null) prefs[DEVICE_TOKEN] = CredentialCipher.encrypt(token)
            else prefs.remove(DEVICE_TOKEN)
        }
    }

    /** Re-saves a key stored in plain text by releases before it was encrypted. */
    suspend fun encryptStoredCredentials() {
        store.edit { prefs ->
            prefs[API_KEY]?.takeIf { !CredentialCipher.isEncrypted(it) }?.let {
                prefs[API_KEY] = CredentialCipher.encrypt(it)
            }
        }
    }

    suspend fun clear() {
        store.edit { it.clear() }
    }

    private companion object {
        val SERVER_URL = stringPreferencesKey("server_url")
        val USERNAME = stringPreferencesKey("username")
        val API_KEY = stringPreferencesKey("api_key")
        val DEVICE_TOKEN = stringPreferencesKey("device_token")
    }
}
