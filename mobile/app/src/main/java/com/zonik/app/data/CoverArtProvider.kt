package com.zonik.app.data

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.ConnectivityManager
import android.net.Uri
import android.os.ParcelFileDescriptor
import com.zonik.app.data.repository.SettingsRepository
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit
import com.zonik.core.model.ServerConfig
import com.zonik.core.util.md5

/**
 * ContentProvider that serves cover art images from the Subsonic server.
 * Used by Android Auto (and other external processes) that can't access
 * the app's OkHttpClient or cleartext HTTP directly.
 *
 * URI format: content://com.zonik.app.artwork/{coverArtId}[/{size}]
 */
class CoverArtProvider : ContentProvider() {

    @EntryPoint
    @InstallIn(SingletonComponent::class)
    interface CoverArtEntryPoint {
        fun settingsRepository(): SettingsRepository
    }

    companion object {
        const val AUTHORITY = "com.zonik.app.artwork"
        @Volatile private var lastErrorLogTime = 0L

        fun buildUri(coverArtId: String, size: Int = 300): Uri {
            return Uri.parse("content://$AUTHORITY/$coverArtId/$size")
        }
    }

    // Background scope that keeps a fresh copy of the server config in memory so
    // openFile() (a synchronous binder/MediaBrowser call) never has to runBlocking
    // on DataStore on every request.
    private val providerScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile private var cachedConfig: ServerConfig? = null

    // Dedicated client with short, bounded timeouts so a slow/timing-out server
    // can never block the binder thread indefinitely (ANR risk for Android Auto).
    private val coverArtClient: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .callTimeout(15, TimeUnit.SECONDS)
            .build()
    }

    override fun onCreate(): Boolean {
        val ctx = context?.applicationContext
        if (ctx != null) {
            val entryPoint = EntryPointAccessors.fromApplication(ctx, CoverArtEntryPoint::class.java)
            val settingsRepository = entryPoint.settingsRepository()
            providerScope.launch {
                settingsRepository.serverConfig.collect { cachedConfig = it }
            }
        }
        return true
    }

    override fun getType(uri: Uri): String = "image/*"

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor? {
        val pathSegments = uri.pathSegments
        if (pathSegments.isEmpty()) return null
        val coverArtId = pathSegments[0]
        val size = pathSegments.getOrNull(1)?.toIntOrNull() ?: 300

        val context = context ?: return null

        // Use the in-memory cached config; only fall back to a short runBlocking on
        // DataStore if the collector hasn't emitted yet (first call after onCreate).
        val config = cachedConfig ?: run {
            val entryPoint = EntryPointAccessors.fromApplication(
                context.applicationContext,
                CoverArtEntryPoint::class.java
            )
            runBlocking { entryPoint.settingsRepository().serverConfig.first() }
        } ?: return null
        val serverUrl = config.url.trimEnd('/')
        val salt = (1..16).map { "abcdefghijklmnopqrstuvwxyz0123456789".random() }.joinToString("")
        val token = md5("${config.apiKey}$salt")
        val url = "$serverUrl/rest/getCoverArt.view?id=$coverArtId&size=$size" +
            "&u=${config.username}&t=$token&s=$salt&v=1.16.1&c=ZonikApp"

        // Cache to disk to avoid re-fetching
        val cacheDir = File(context.cacheDir, "cover_art")
        cacheDir.mkdirs()
        val cacheFile = File(cacheDir, "${coverArtId}_$size")
        if (cacheFile.exists() && cacheFile.length() > 0) {
            return ParcelFileDescriptor.open(cacheFile, ParcelFileDescriptor.MODE_READ_ONLY)
        }

        // Skip network call if offline — avoids DNS crash and error spam
        val cm = context.getSystemService(ConnectivityManager::class.java)
        if (cm?.activeNetwork == null) return null

        return try {
            val request = Request.Builder().url(url).build()
            val response = coverArtClient.newCall(request).execute()
            if (!response.isSuccessful) return null
            val bytes = response.body?.bytes() ?: return null
            cacheFile.writeBytes(bytes)
            ParcelFileDescriptor.open(cacheFile, ParcelFileDescriptor.MODE_READ_ONLY)
        } catch (e: Exception) {
            // Throttle error logging to avoid spam (1 log per 30s)
            val now = System.currentTimeMillis()
            if (now - lastErrorLogTime > 30_000) {
                lastErrorLogTime = now
                DebugLog.w("CoverArtProvider", "Failed to fetch cover art: ${e.message}")
            }
            null
        }
    }

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
