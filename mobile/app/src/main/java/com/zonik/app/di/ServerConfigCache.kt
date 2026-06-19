package com.zonik.app.di

import com.zonik.app.data.repository.SettingsRepository
import com.zonik.core.model.ServerConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Holds the latest [ServerConfig] in a @Volatile field so OkHttp interceptors
 * can read it synchronously off a dispatcher thread instead of doing a
 * `runBlocking { settingsRepository.serverConfig.first() }` on every request
 * (which blocks the thread on DataStore I/O).
 *
 * A single long-lived collector keeps the cache current; an initial blocking
 * read in [init] seeds it so the very first request isn't null.
 */
@Singleton
class ServerConfigCache @Inject constructor(
    private val settingsRepository: SettingsRepository
) {
    @Volatile
    private var cached: ServerConfig? = null

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    init {
        // Seed once so the first request has a value before the collector runs.
        cached = runBlocking { settingsRepository.serverConfig.first() }
        scope.launch {
            settingsRepository.serverConfig.collect { cached = it }
        }
    }

    /**
     * Latest known server config, read synchronously (called from OkHttp
     * interceptor threads). Falls back to a one-shot blocking read when the
     * cache is still cold — e.g. a request fired immediately after first login,
     * before the async collector observed the write — so we never fall back to
     * the placeholder base URL with null/stale auth. Steady-state reads hit the
     * @Volatile field with no blocking.
     */
    fun current(): ServerConfig? {
        cached?.let { return it }
        return runBlocking { settingsRepository.serverConfig.first() }.also { cached = it }
    }
}
