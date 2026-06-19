package com.zonik.app.data.api

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.zonik.app.data.DebugLog
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import okhttp3.Dns
import java.net.InetAddress
import java.net.UnknownHostException
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dnsCacheDataStore by preferencesDataStore(name = "dns_cache")

private const val DNS_CACHE_TTL_MS = 24L * 60 * 60 * 1000 // 24h

@Singleton
class CachingDns @Inject constructor(
    @ApplicationContext context: Context,
) : Dns {
    private val store = context.dnsCacheDataStore
    private val mem = ConcurrentHashMap<String, CacheEntry>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private data class CacheEntry(val addrs: List<InetAddress>, val expiresAt: Long)

    init {
        scope.launch {
            try {
                val now = System.currentTimeMillis()
                val prefs = store.data.first()
                for ((k, v) in prefs.asMap()) {
                    if (k is Preferences.Key<*> && v is String && v.isNotBlank()) {
                        try {
                            // Persisted as "ip,ip,...;expiresAt"
                            val parts = v.split(";")
                            val expiresAt = parts.getOrNull(1)?.toLongOrNull() ?: 0L
                            if (expiresAt <= now) continue
                            val addrs = parts[0].split(",")
                                .filter { it.isNotBlank() }
                                .map { InetAddress.getByName(it) }
                            if (addrs.isNotEmpty()) {
                                mem[k.name] = CacheEntry(addrs, expiresAt)
                            }
                        } catch (_: Exception) { }
                    }
                }
                DebugLog.d("CachingDns", "Restored ${mem.size} cached DNS entries")
            } catch (e: Exception) {
                DebugLog.w("CachingDns", "DNS cache restore failed: ${e.message}")
            }
        }
    }

    override fun lookup(hostname: String): List<InetAddress> {
        return try {
            val addrs = Dns.SYSTEM.lookup(hostname)
            if (addrs.isNotEmpty()) cache(hostname, addrs)
            addrs
        } catch (e: UnknownHostException) {
            val cached = mem[hostname]
            if (cached != null && cached.expiresAt > System.currentTimeMillis()) {
                DebugLog.w("CachingDns", "DNS failed for $hostname; using cached ${cached.addrs.first().hostAddress}")
                cached.addrs
            } else {
                if (cached != null) {
                    DebugLog.w("CachingDns", "DNS failed for $hostname; cached entry expired, failing fast")
                    mem.remove(hostname)
                }
                throw e
            }
        }
    }

    private fun cache(hostname: String, addrs: List<InetAddress>) {
        val expiresAt = System.currentTimeMillis() + DNS_CACHE_TTL_MS
        mem[hostname] = CacheEntry(addrs, expiresAt)
        val ips = addrs.mapNotNull { it.hostAddress }
        if (ips.isEmpty()) return
        scope.launch {
            try {
                store.edit {
                    it[stringPreferencesKey(hostname)] = "${ips.joinToString(",")};$expiresAt"
                }
            } catch (_: Exception) { }
        }
    }
}
