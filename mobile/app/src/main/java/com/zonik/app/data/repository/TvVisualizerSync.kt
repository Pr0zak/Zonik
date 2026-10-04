package com.zonik.app.data.repository

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build
import android.provider.Settings
import com.zonik.app.data.DebugLog
import com.zonik.app.data.api.TvVisualizerConfig
import com.zonik.app.data.api.TvVisualizerConfigUpdate
import com.zonik.app.data.api.TvVisualizerStatsReport
import com.zonik.app.data.api.ZonikApi
import com.zonik.app.ui.tv.TvEffectStats
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.security.MessageDigest
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Keeps the TV visualizer's settings in step with the server, which holds the one shared copy
 * (edited from the web UI's TV Visualizer page), and uploads per-effect stats.
 *
 * - [pull] fetches the server's settings and writes them into [SettingsRepository]. It writes
 *   straight to the repository, never through [push], so a pull is never echoed back.
 * - [push] sends a setting changed on the TV. If the server cannot be reached the change is
 *   kept and retried before the next pull, so a pull never quietly undoes it.
 * - A server nobody has saved settings on yet is seeded from this TV's current settings, so
 *   upgrading the app does not reset a TV that was already set up.
 */
@Singleton
class TvVisualizerSync @Inject constructor(
    private val api: ZonikApi,
    private val settings: SettingsRepository,
    @ApplicationContext private val context: Context,
) {
    // Stats are flushed when the TV screen closes, after its view model's scope is gone.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lock = Mutex()
    private var pending: TvVisualizerConfig? = null

    val deviceName: String = "${Build.MANUFACTURER} ${Build.MODEL}".trim()

    /** A stable, anonymous id for this TV: a hash of ANDROID_ID, never the id itself. */
    @SuppressLint("HardwareIds")
    val deviceId: String = run {
        val raw = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: deviceName
        MessageDigest.getInstance("SHA-256").digest(raw.toByteArray())
            .take(8).joinToString("") { "%02x".format(it) }
    }

    suspend fun pull() = lock.withLock {
        try {
            pending?.let { sendLocked(it) }
            val remote = api.getTvVisualizerConfig()
            if (remote.updatedAt == null) {
                DebugLog.d("TvSync", "Server has no visualizer settings yet; seeding from this TV")
                sendLocked(current())
                return@withLock
            }
            apply(remote.config)
        } catch (e: Exception) {
            DebugLog.d("TvSync", "Visualizer settings pull failed: ${e.message}")
        }
    }

    fun push(change: TvVisualizerConfig) {
        scope.launch {
            lock.withLock {
                pending = merge(pending, change)
                try {
                    sendLocked(pending!!)
                } catch (e: Exception) {
                    DebugLog.d("TvSync", "Visualizer settings push failed, will retry: ${e.message}")
                }
            }
        }
    }

    /** Sends [change] and clears what was pending. Caller holds [lock]. */
    private suspend fun sendLocked(change: TvVisualizerConfig) {
        api.putTvVisualizerConfig(TvVisualizerConfigUpdate(change, updatedBy = deviceName))
        pending = null
    }

    /** Uploads the effect stats gathered since the last upload; puts them back on failure. */
    fun uploadStats() {
        scope.launch {
            val reports = TvEffectStats.drain().filter { it.seconds > 0f || it.shows > 0 }
            if (reports.isEmpty()) return@launch
            try {
                api.postTvVisualizerStats(TvVisualizerStatsReport(deviceId, deviceName, reports))
                DebugLog.d("TvSync", "Uploaded stats for ${reports.size} effects")
            } catch (e: Exception) {
                TvEffectStats.restore(reports)
                DebugLog.d("TvSync", "Stats upload failed, kept for next time: ${e.message}")
            }
        }
    }

    private suspend fun current() = TvVisualizerConfig(
        enabled = settings.tvAmbientEnabled.first(),
        delaySec = settings.tvAmbientDelaySec.first(),
        beatReactive = settings.tvAmbientBeatReactive.first(),
        effectsOff = settings.tvAmbientEffectsOff.first().sorted(),
        rotateSec = settings.tvAmbientRotateSec.first(),
        info = settings.tvAmbientInfo.first(),
        transition = settings.tvAmbientTransition.first(),
        transitionMs = settings.tvAmbientTransitionMs.first(),
        colors = settings.tvAmbientColors.first(),
        trails = settings.tvAmbientTrails.first(),
    )

    /** Writes the server's values, skipping any that already match so DataStore is not churned. */
    private suspend fun apply(c: TvVisualizerConfig) {
        val now = current()
        var changed = 0
        suspend fun <T> set(remote: T?, local: T?, write: suspend (T) -> Unit) {
            if (remote != null && remote != local) {
                write(remote)
                changed++
            }
        }
        set(c.enabled, now.enabled) { settings.setTvAmbientEnabled(it) }
        set(c.delaySec, now.delaySec) { settings.setTvAmbientDelaySec(it) }
        set(c.beatReactive, now.beatReactive) { settings.setTvAmbientBeatReactive(it) }
        set(c.effectsOff?.sorted(), now.effectsOff) { settings.setTvAmbientEffectsOff(it.toSet()) }
        set(c.rotateSec, now.rotateSec) { settings.setTvAmbientRotateSec(it) }
        set(c.info, now.info) { settings.setTvAmbientInfo(it) }
        set(c.transition, now.transition) { settings.setTvAmbientTransition(it) }
        set(c.transitionMs, now.transitionMs) { settings.setTvAmbientTransitionMs(it) }
        set(c.colors, now.colors) { settings.setTvAmbientColors(it) }
        set(c.trails, now.trails) { settings.setTvAmbientTrails(it) }
        if (changed > 0) DebugLog.d("TvSync", "Applied $changed visualizer settings from the server")
    }

    private fun merge(a: TvVisualizerConfig?, b: TvVisualizerConfig) = if (a == null) b else TvVisualizerConfig(
        enabled = b.enabled ?: a.enabled,
        delaySec = b.delaySec ?: a.delaySec,
        beatReactive = b.beatReactive ?: a.beatReactive,
        effectsOff = b.effectsOff ?: a.effectsOff,
        rotateSec = b.rotateSec ?: a.rotateSec,
        info = b.info ?: a.info,
        transition = b.transition ?: a.transition,
        transitionMs = b.transitionMs ?: a.transitionMs,
        colors = b.colors ?: a.colors,
        trails = b.trails ?: a.trails,
    )
}
