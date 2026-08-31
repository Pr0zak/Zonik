package com.zonik.app.media

import android.content.ComponentName
import android.content.Context
import com.zonik.app.ui.util.isTvDevice
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import com.zonik.app.data.DebugLog
import com.zonik.app.data.repository.LibraryRepository
import com.zonik.app.data.repository.SettingsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import com.zonik.core.model.ServerConfig
import com.zonik.core.model.Track
import dagger.hilt.android.qualifiers.ApplicationContext
import com.google.common.util.concurrent.MoreExecutors
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import com.zonik.core.util.md5
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class PlaybackManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val settingsRepository: SettingsRepository,
    private val libraryRepository: LibraryRepository,
    val castManager: CastManager,
    private val offlineCacheManager: OfflineCacheManager
) {
    private val scope = CoroutineScope(Dispatchers.IO)
    private var controller: MediaController? = null
    @Volatile private var cachedServerConfig: ServerConfig? = null
    @Volatile private var cachedWifiBitrate: Int = 0
    @Volatile private var cachedCellularBitrate: Int = 192

    init {
        scope.launch {
            settingsRepository.serverConfig.collect { config ->
                cachedServerConfig = config
            }
        }
        scope.launch {
            settingsRepository.wifiBitrate.collect { bitrate ->
                cachedWifiBitrate = bitrate
            }
        }
        scope.launch {
            settingsRepository.cellularBitrate.collect { bitrate ->
                cachedCellularBitrate = bitrate
            }
        }
        scope.launch {
            settingsRepository.adaptiveBitrate.collect { enabled ->
                adaptiveBitrateEnabled = enabled
                if (!enabled) resetBitrate()
            }
        }
    }

    // Set by skipToIndex to prevent onMediaItemTransition from overriding
    // the correct track when manually seeking within the queue.
    private var _manualSeekIndex: Int = -1

    // After a manual seek, ExoPlayer fires two transitions: reason=2 (SEEK) then
    // reason=3 (AUTO). We must ignore the second one to avoid overriding the track.
    private var _ignoreNextAutoTransition: Boolean = false

    private val _currentTrack = MutableStateFlow<Track?>(null)
    val currentTrack: StateFlow<Track?> = _currentTrack.asStateFlow()

    private val _isPlaying = MutableStateFlow(false)
    val isPlaying: StateFlow<Boolean> = _isPlaying.asStateFlow()

    private val _isBuffering = MutableStateFlow(false)
    val isBuffering: StateFlow<Boolean> = _isBuffering.asStateFlow()

    private val _playbackError = MutableStateFlow<String?>(null)
    val playbackError: StateFlow<String?> = _playbackError.asStateFlow()

    // Adaptive bitrate: step down on connection issues, restore when stable
    private val bitrateSteps = listOf(0, 320, 256, 192, 128, 64) // 0 = original
    @Volatile private var bitrateOverride: Int? = null
    @Volatile private var stableTrackCount = 0
    @Volatile private var adaptiveBitrateEnabled = true
    // Rolling window: track buffering event timestamps instead of a simple counter
    // (counter resets on every READY, which happens between every buffer event, so it never reaches 3)
    private val bufferingTimestamps = mutableListOf<Long>()

    private val _queue = MutableStateFlow<List<Track>>(emptyList())
    val queue: StateFlow<List<Track>> = _queue.asStateFlow()

    private val _recentlyPlayed = MutableStateFlow<List<Track>>(emptyList())
    val recentlyPlayed: StateFlow<List<Track>> = _recentlyPlayed.asStateFlow()

    private val _playbackRequested = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val playbackRequested: Flow<Unit> = _playbackRequested

    // Throttle position saves to every 10 seconds. Scrobbles + now-playing are
    // handled in ZonikMediaService so they fire whether or not the UI is visible.
    @Volatile private var lastPositionSaveTime = 0L

    /** A play request that arrived before the MediaController was ready. Single slot: if the
     *  user presses two tiles while we are still connecting, they meant the second one. */
    private data class PendingPlay(
        val tracks: List<Track>,
        val startIndex: Int,
        val startPaused: Boolean,
        val requestedAtMs: Long,
    )

    @Volatile private var pendingPlay: PendingPlay? = null

    /** Starting music by surprise, long after the press, is its own bad experience. */
    private val pendingPlayMaxAgeMs = 30_000L

    /** The optimistic UI update: queue and current track land before ExoPlayer confirms, so the
     *  screen reacts to the press immediately. Only call this once the request will really run. */
    private fun publishPlayIntent(tracks: List<Track>, startIndex: Int) {
        _queue.value = tracks
        if (startIndex in tracks.indices) {
            _currentTrack.value = tracks[startIndex]
        }
        _playbackRequested.tryEmit(Unit)
    }

    suspend fun connect() {
        if (controller != null) return
        DebugLog.d("Playback", "Connecting to MediaService...")
        val sessionToken = SessionToken(
            context,
            ComponentName(context, ZonikMediaService::class.java)
        )
        val future = MediaController.Builder(context, sessionToken).buildAsync()
        controller = suspendCoroutine { cont ->
            future.addListener(
                { cont.resume(future.get()) },
                MoreExecutors.directExecutor()
            )
        }

        DebugLog.d("Playback", "Connected to MediaService")

        // A press that landed while we were connecting wins over everything below: it is the
        // only one of these the user actually asked for. Replaying it fills _queue, which also
        // makes the two restore paths below no-op on their own guards — deliberately, since
        // restoring a saved queue over the user's choice would then seek it to a stale position.
        pendingPlay?.let { pending ->
            pendingPlay = null
            val ageMs = System.currentTimeMillis() - pending.requestedAtMs
            if (ageMs > pendingPlayMaxAgeMs) {
                DebugLog.d("Playback", "Dropping deferred play request — ${ageMs}ms stale")
            } else {
                DebugLog.d("Playback", "Replaying deferred play request: ${pending.tracks.size} tracks")
                playTracks(pending.tracks, pending.startIndex, pending.startPaused)
            }
        }

        // Restore queue from player's current media items (e.g. after playback resumption)
        if (_queue.value.isEmpty() && (controller?.mediaItemCount ?: 0) > 0) {
            syncQueueFromPlayer()
        }

        // If player is empty after process kill, restore saved queue from DataStore
        // Skip on TV — user just shuffles, no need to restore old queue
        val isTv = context.isTvDevice()
        if (!isTv && _queue.value.isEmpty() && (controller?.mediaItemCount ?: 0) == 0) {
            scope.launch {
                try {
                    val savedTrackIds = settingsRepository.lastQueueTrackIds.first()
                    val savedIndex = settingsRepository.lastQueueIndex.first()
                    val savedPosition = settingsRepository.lastQueuePositionMs.first()
                    if (savedTrackIds.isNotEmpty()) {
                        // Padded: savedIndex was recorded against the full saved list, so
                        // dropping a track the DB no longer has would resume on the wrong song.
                        // A placeholder still streams — the URL only needs the id.
                        val resolved = libraryRepository.getTracksByIdsPadded(savedTrackIds)
                        if (resolved.any { it != null }) {
                            val tracks = resolved.mapIndexed { i, track ->
                                track ?: Track(id = savedTrackIds[i], title = savedTrackIds[i])
                            }
                            val startIndex = savedIndex.coerceIn(0, tracks.size - 1)
                            DebugLog.d("Playback", "Restoring saved queue: ${tracks.size} tracks, index=$startIndex, pos=${savedPosition}ms")
                            withContext(Dispatchers.Main) {
                                playTracks(tracks, startIndex, startPaused = true)
                            }
                            // Seek to saved position after player loads
                            delay(1000)
                            withContext(Dispatchers.Main) {
                                controller?.seekTo(savedPosition)
                            }
                        }
                    }
                } catch (e: Exception) {
                    DebugLog.w("Playback", "Queue restore failed: ${e.message}")
                }
            }
        }

        // Track Cast track changes and update currentTrack
        scope.launch(Dispatchers.Main) {
            castManager.castTrackTitle.collect { title ->
                if (title != null && castManager.isCasting.value) {
                    val artist = castManager.castTrackArtist.value
                    val match = _queue.value.find { it.title == title && (artist == null || it.artist == artist) }
                    if (match != null && match.id != _currentTrack.value?.id) {
                        setCurrentTrack(match)
                        DebugLog.d("Playback", "Cast track update: ${match.title} by ${match.artist}")
                    }
                }
            }
        }

        // When Cast session starts, transfer current playback to Cast device
        scope.launch(Dispatchers.Main) {
            castManager.isCasting.collect { casting ->
                if (casting) {
                    val queue = _queue.value
                    val track = _currentTrack.value
                    if (queue.isNotEmpty() && track != null) {
                        val startIndex = queue.indexOfFirst { it.id == track.id }.coerceAtLeast(0)
                        val config = getServerConfig() ?: return@collect
                        val serverUrl = config.url

                        // Pause local playback
                        controller?.pause()

                        DebugLog.d("Playback", "Transferring ${queue.size} tracks to Cast (starting at $startIndex)")
                        castManager.loadQueue(
                            tracks = queue,
                            startIndex = startIndex,
                            buildStreamUrl = { t -> buildStreamUrl(t, serverUrl, config) },
                            buildArtUrl = { t -> buildArtUrl(t, serverUrl, config) }
                        )
                    }
                }
            }
        }

        controller?.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(playing: Boolean) {
                DebugLog.d("Playback", "isPlaying changed: $playing")
                _isPlaying.value = playing
            }

            override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
                val index = controller?.currentMediaItemIndex ?: -1
                val metaTitle = mediaItem?.mediaMetadata?.title?.toString()
                val metaArtist = mediaItem?.mediaMetadata?.artist?.toString()
                DebugLog.d("Playback", "Track transition: title='$metaTitle' artist='$metaArtist' index=$index reason=$reason manualSeek=$_manualSeekIndex")

                // After a manual seek, ignore the follow-up AUTO transition
                if (_ignoreNextAutoTransition && reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO) {
                    _ignoreNextAutoTransition = false
                    DebugLog.d("Playback", "Ignoring post-seek AUTO transition")
                    return
                }

                // Manual seek from skipToIndex — trust our index, ignore ExoPlayer's
                if (_manualSeekIndex >= 0) {
                    val expected = _manualSeekIndex
                    _manualSeekIndex = -1
                    _ignoreNextAutoTransition = true
                    DebugLog.d("Playback", "Manual seek: using index $expected (ExoPlayer reported $index)")
                    updateCurrentTrackByIndex(expected)
                    return
                }

                // PLAYLIST_CHANGED fires when the service sets items on the player directly
                // Skip duplicate transitions for the same track (prevents UI flicker and extra scrobbles)
                val current = _currentTrack.value
                val transitionId = mediaItem?.mediaId?.takeIf { it.isNotBlank() }?.let { bareTrackId(it) }
                if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_PLAYLIST_CHANGED
                    && current != null && metaTitle == current.title
                    // Titles alone would call two adjacent placeholder items the same track
                    // and swallow the transition between them.
                    && (transitionId == null || transitionId == current.id)
                    && (metaArtist == null || metaArtist == current.artist)) {
                    DebugLog.d("Playback", "Skipping duplicate PLAYLIST_CHANGED for '${current.title}'")
                    return
                }

                // Any real track change clears the post-seek ignore flag
                _ignoreNextAutoTransition = false

                // Media id first: it is exact, whereas titles collide — most sharply among
                // tracks the local DB doesn't have, which share whatever placeholder name the
                // fallback gave them.
                if (transitionId != null) {
                    val match = _queue.value.find { it.id == transitionId }
                    if (match != null) {
                        setCurrentTrack(match)
                        return
                    }
                }
                // Then metadata (still more reliable than index after shuffle/IPC)
                if (metaTitle != null) {
                    val match = findTrackByMetadata(metaTitle, metaArtist)
                    if (match != null) {
                        setCurrentTrack(match)
                        return
                    }
                }
                updateCurrentTrackByIndex(index)
            }

            override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                DebugLog.e("Playback", "Player error: ${error.errorCodeName} - ${error.message}")
                DebugLog.e("Playback", "Error cause: ${error.cause?.message}")
                val isNetworkError = error.errorCode == androidx.media3.common.PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED
                    || error.errorCode == androidx.media3.common.PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT
                    || error.errorCode == androidx.media3.common.PlaybackException.ERROR_CODE_IO_UNSPECIFIED
                _playbackError.value = if (isNetworkError) "Connection lost — retrying..." else "Playback error"
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                val state = when (playbackState) {
                    Player.STATE_IDLE -> "IDLE"
                    Player.STATE_BUFFERING -> "BUFFERING"
                    Player.STATE_READY -> "READY"
                    Player.STATE_ENDED -> "ENDED"
                    else -> "UNKNOWN($playbackState)"
                }
                DebugLog.d("Playback", "State: $state")
                _isBuffering.value = playbackState == Player.STATE_BUFFERING
                if (playbackState == Player.STATE_READY) {
                    _playbackError.value = null
                    // Auto-restore bitrate after 3 consecutive stable tracks
                    if (bitrateOverride != null) {
                        stableTrackCount++
                        if (stableTrackCount >= 3) {
                            resetBitrate()
                        }
                    }
                }
                if (playbackState == Player.STATE_BUFFERING) {
                    val now = System.currentTimeMillis()
                    bufferingTimestamps.add(now)
                    // Keep only events from the last 2 minutes
                    bufferingTimestamps.removeAll { now - it > 120_000 }
                    DebugLog.d("Playback", "Buffering events in window: ${bufferingTimestamps.size}, adaptive=$adaptiveBitrateEnabled, override=$bitrateOverride")
                    if (bufferingTimestamps.size >= 3 && adaptiveBitrateEnabled) {
                        degradeBitrate()
                        bufferingTimestamps.clear()
                    }
                }
            }
        })

        // Restore equalizer settings (must be on main thread for MediaController)
        kotlinx.coroutines.CoroutineScope(Dispatchers.Main).launch {
            try {
                val enabled = settingsRepository.eqEnabled.first()
                val preset = settingsRepository.eqPreset.first()
                val bandLevels = settingsRepository.eqBandLevels.first()
                applyEqualizerSettings(enabled, preset, bandLevels)
            } catch (e: Exception) {
                DebugLog.w("Playback", "EQ restore failed: ${e.message}")
            }
        }
    }

    fun playTracks(tracks: List<Track>, startIndex: Int = 0, startPaused: Boolean = false) {
        val config = getServerConfig() ?: return
        val serverUrl = config.url
        // Cap track list to avoid TransactionTooLargeException (Binder 1MB limit)
        val maxTracks = 500
        val cappedTracks = if (tracks.size > maxTracks) {
            val start = maxOf(0, startIndex - 50) // keep some context before start
            val end = minOf(tracks.size, start + maxTracks)
            val adjustedIndex = startIndex - start
            DebugLog.d("Playback", "Capping ${tracks.size} tracks to $maxTracks (offset $start, adjusted index $adjustedIndex)")
            return playTracks(tracks.subList(start, end), adjustedIndex, startPaused)
        } else tracks
        // Route to Cast if a Cast session is active
        if (castManager.isCasting.value) {
            publishPlayIntent(cappedTracks, startIndex)
            DebugLog.d("Playback", "Casting ${tracks.size} tracks from index $startIndex")
            castManager.loadQueue(
                tracks = tracks,
                startIndex = startIndex,
                buildStreamUrl = { track -> buildStreamUrl(track, serverUrl, config) },
                buildArtUrl = { track -> buildArtUrl(track, serverUrl, config) }
            )
            return
        }

        val ctrl = controller
        if (ctrl == null) {
            // Reachable for the first few seconds of a cold start, and on TV that is exactly
            // when someone presses a shuffle tile. Hold the request and replay it once connect()
            // finishes instead of dropping it — and publish nothing yet, because the optimistic
            // state below would otherwise put a Now Playing screen in front of a track that is
            // never going to start.
            pendingPlay = PendingPlay(cappedTracks, startIndex, startPaused, System.currentTimeMillis())
            DebugLog.w("Playback", "playTracks before the controller connected — deferring ${cappedTracks.size} tracks")
            return
        }

        publishPlayIntent(cappedTracks, startIndex)
        DebugLog.d("Playback", "Playing ${tracks.size} tracks from index $startIndex")

        // Send track IDs via custom command to avoid Media3 per-item IPC reordering.
        // The service sets items directly on the player, preserving order.
        val args = android.os.Bundle().apply {
            putStringArrayList("track_ids", ArrayList(cappedTracks.map { it.id }))
            // Display fields travel with the ids so a track the local scan hasn't picked up yet
            // still shows a title on the notification, lock screen, Android Auto and Wear — all
            // of which read the session's metadata, not our in-process queue. Cheap: a few tens
            // of KB at the 500-track cap, well inside the Binder budget the cap exists for.
            putStringArrayList("track_titles", ArrayList(cappedTracks.map { it.title }))
            putStringArrayList("track_artists", ArrayList(cappedTracks.map { it.artist }))
            putStringArrayList("track_albums", ArrayList(cappedTracks.map { it.album }))
            putStringArrayList("track_cover_art", ArrayList(cappedTracks.map { it.coverArt ?: "" }))
            putInt("start_index", startIndex)
            if (startPaused) putBoolean("start_paused", true)
        }
        ctrl.sendCustomCommand(
            androidx.media3.session.SessionCommand("com.zonik.app.PLAY_TRACKS", android.os.Bundle.EMPTY),
            args
        )

        // Auto-cache queue for offline if enabled
        if (!startPaused) {
            scope.launch {
                try {
                    val enabled = settingsRepository.offlineCacheEnabled.first()
                    val autoCacheQueue = settingsRepository.autoCacheQueue.first()
                    if (enabled && autoCacheQueue) {
                        offlineCacheManager.downloadTracks(tracks.map { it.id })
                    }
                } catch (_: Exception) {}
            }
        }
    }

    fun playNext(track: Track) {
        val ctrl = controller ?: return
        val config = getServerConfig() ?: return
        val nextIndex = ctrl.currentMediaItemIndex + 1
        ctrl.addMediaItem(nextIndex, buildMediaItem(track, config.url, config))

        val updatedQueue = _queue.value.toMutableList()
        updatedQueue.add(nextIndex, track)
        _queue.value = updatedQueue
    }

    fun addToQueue(track: Track) {
        val ctrl = controller ?: return
        val config = getServerConfig() ?: return
        ctrl.addMediaItem(buildMediaItem(track, config.url, config))

        _queue.value = _queue.value + track
    }

    fun togglePlayPause() {
        if (castManager.isCasting.value) {
            castManager.togglePlayPause()
            _isPlaying.value = !_isPlaying.value
            return
        }
        val ctrl = controller ?: return
        if (ctrl.isPlaying) ctrl.pause() else ctrl.play()
    }

    fun seekTo(positionMs: Long) {
        if (castManager.isCasting.value) {
            castManager.seekTo(positionMs)
            return
        }
        controller?.seekTo(positionMs)
    }

    fun skipToIndex(index: Int) {
        val ctrl = controller ?: return
        val track = _queue.value.getOrNull(index) ?: return
        DebugLog.d("Playback", "skipToIndex: $index (mediaItemCount=${ctrl.mediaItemCount}, queueSize=${_queue.value.size})")

        // ExoPlayer's internal queue may differ from _queue due to IPC reordering.
        // Find the track by mediaId or metadata in ExoPlayer's actual queue.
        var exoIndex = -1
        for (i in 0 until ctrl.mediaItemCount) {
            val item = ctrl.getMediaItemAt(i)
            if (item.mediaId == track.id) {
                exoIndex = i
                break
            }
            // Fallback: match by title (mediaId may be empty after IPC)
            val title = item.mediaMetadata.title?.toString()
            if (title != null && title == track.title) {
                exoIndex = i
                break
            }
        }
        if (exoIndex < 0) {
            if (ctrl.mediaItemCount == 0 && _queue.value.isNotEmpty()) {
                // Controller hasn't synced yet after PLAY_TRACKS — use queue index directly
                DebugLog.d("Playback", "skipToIndex: controller not synced, using queue index $index")
                exoIndex = index
            } else if (ctrl.mediaItemCount == 0) {
                DebugLog.w("Playback", "skipToIndex: player is empty, cannot skip")
                return
            } else {
                DebugLog.w("Playback", "skipToIndex: track '${track.title}' (${track.id}) not found in ExoPlayer queue, falling back to index $index")
                exoIndex = index.coerceIn(0, ctrl.mediaItemCount - 1)
            }
        }
        if (exoIndex != index) {
            DebugLog.d("Playback", "skipToIndex: queue index $index maps to ExoPlayer index $exoIndex")
        }

        _manualSeekIndex = index  // Tell onMediaItemTransition to use our queue index
        _ignoreNextAutoTransition = false
        setCurrentTrack(track)  // Update UI immediately
        ctrl.seekTo(exoIndex, 0L)
    }

    fun skipNext() {
        if (castManager.isCasting.value) {
            castManager.skipNext()
            return
        }
        val ctrl = controller
        if (ctrl == null) {
            DebugLog.w("Playback", "skipNext: controller is null")
            return
        }
        DebugLog.d("Playback", "skipNext: index=${ctrl.currentMediaItemIndex}, count=${ctrl.mediaItemCount}")
        ctrl.seekToNext()
    }

    fun skipPrevious() {
        if (castManager.isCasting.value) {
            castManager.skipPrevious()
            return
        }
        val ctrl = controller
        if (ctrl == null) {
            DebugLog.w("Playback", "skipPrevious: controller is null")
            return
        }
        DebugLog.d("Playback", "skipPrevious: index=${ctrl.currentMediaItemIndex}, count=${ctrl.mediaItemCount}")
        ctrl.seekToPrevious()
    }

    fun setShuffleEnabled(enabled: Boolean) {
        controller?.shuffleModeEnabled = enabled
    }

    fun setRepeatMode(mode: Int) {
        controller?.repeatMode = mode
    }

    fun setPlaybackSpeed(speed: Float) {
        controller?.setPlaybackParameters(androidx.media3.common.PlaybackParameters(speed))
    }

    fun getCurrentPosition(): Long {
        if (castManager.isCasting.value) {
            val pos = castManager.getCurrentPosition()
            maybePersistPosition()
            return pos
        }
        val pos = controller?.currentPosition ?: 0L
        maybePersistPosition()
        return pos
    }

    fun getDuration(): Long {
        if (castManager.isCasting.value) return castManager.getDuration()
        return controller?.duration ?: 0L
    }

    private fun maybePersistPosition() {
        if (_currentTrack.value == null) return
        // Periodically save position for resume (every 10s).
        val now = System.currentTimeMillis()
        if (now - lastPositionSaveTime > 10_000) {
            lastPositionSaveTime = now
            savePositionNow()
        }
    }

    fun release() {
        // Save position before disconnecting so resume picks up here
        savePositionNow()
        controller?.release()
        controller = null
    }

    /** Save current position immediately (called on release and periodically) */
    private fun savePositionNow() {
        val queue = _queue.value
        if (queue.isEmpty()) return
        val track = _currentTrack.value ?: return
        val index = queue.indexOfFirst { it.id == track.id }.coerceAtLeast(0)
        // controller.currentPosition must be on main thread — if we're already there, read directly
        if (android.os.Looper.myLooper() == android.os.Looper.getMainLooper()) {
            val position = controller?.currentPosition?.coerceAtLeast(0L) ?: 0L
            scope.launch {
                settingsRepository.savePlaybackState(queue.map { it.id }, index, position)
            }
        } else {
            // Post to main to read position, then save
            val trackIds = queue.map { it.id }
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                val position = controller?.currentPosition?.coerceAtLeast(0L) ?: 0L
                scope.launch {
                    settingsRepository.savePlaybackState(trackIds, index, position)
                }
            }
        }
    }

    private fun buildStreamUrl(track: Track, serverUrl: String, config: ServerConfig): String {
        val bitrate = getMaxBitRate()
        val bitrateParam = if (bitrate > 0) "&maxBitRate=$bitrate" else ""
        val authParams = buildAuthParamsFromConfig(config)
        return "${serverUrl.trimEnd('/')}/rest/stream.view?id=${track.id}${bitrateParam}&estimateContentLength=true$authParams"
    }

    private fun buildArtUrl(track: Track, serverUrl: String, config: ServerConfig): String? {
        val authParams = buildAuthParamsFromConfig(config)
        return track.coverArt?.let {
            "${serverUrl.trimEnd('/')}/rest/getCoverArt.view?id=$it&size=600$authParams"
        }
    }

    private fun buildMediaItem(track: Track, serverUrl: String, config: ServerConfig): MediaItem {
        val streamUrl = buildStreamUrl(track, serverUrl, config)
        // Use ContentProvider URI for artwork so Android Auto can fetch it
        val artUri = track.coverArt?.let {
            com.zonik.app.data.CoverArtProvider.buildUri(it, 600)
        }

        return MediaItem.Builder()
            .setMediaId(track.id)
            .setUri(streamUrl)
            .setRequestMetadata(
                MediaItem.RequestMetadata.Builder()
                    .setMediaUri(Uri.parse(streamUrl))
                    .build()
            )
            .setMediaMetadata(
                MediaMetadata.Builder()
                    .setTitle(track.title)
                    .setArtist(track.artist)
                    .setAlbumTitle(track.album)
                    .setTrackNumber(track.track)
                    .setArtworkUri(artUri)
                    .build()
            )
            .build()
    }

    private fun buildAuthParamsFromConfig(config: ServerConfig): String {
        val salt = (1..16).map { "abcdefghijklmnopqrstuvwxyz0123456789".random() }.joinToString("")
        val token = md5("${config.apiKey}$salt")
        return "&u=${config.username}&t=$token&s=$salt&v=1.16.1&c=ZonikApp"
    }

    private fun findTrackByMetadata(title: String, artist: String?): Track? {
        val queue = _queue.value
        return queue.find { it.title == title && (artist == null || it.artist == artist) }
    }

    /**
     * One player timeline slot, snapshotted on the main thread. Carries the metadata the
     * service published so a track the local DB has never seen still has a name, an album and
     * artwork inside the app — the same fields the notification already shows for it.
     */
    private data class QueueSlot(
        val id: String,
        val title: String,
        val artist: String,
        val album: String,
        val coverArt: String?,
    ) {
        fun toPlaceholderTrack(): Track = Track(
            id = id,
            // Falling back to the id rather than a constant keeps placeholders distinct:
            // findTrackByMetadata matches on title, so two identically-named slots would
            // otherwise both resolve to the first one.
            title = title.ifEmpty { id },
            artist = artist,
            album = album,
            coverArt = coverArt,
        )
    }

    private fun setCurrentTrack(track: Track) {
        DebugLog.d("Playback", "Now playing: ${track.title} by ${track.artist}")
        _currentTrack.value = track
        addToRecentlyPlayed(track)
        persistPlaybackState()
        // ZonikMediaService posts now-playing + scrobbles via its own Player.Listener,
        // so it fires whether or not the UI is visible (incl. Android Auto).
    }

    private fun persistPlaybackState() {
        // Read queue/track from StateFlows (thread-safe) and position on main thread
        val queue = _queue.value
        if (queue.isEmpty()) return
        val trackIds = queue.map { it.id }
        val index = queue.indexOfFirst { it.id == _currentTrack.value?.id }.coerceAtLeast(0)
        // During Cast, use castManager position (avoids main-thread requirement for controller)
        val position = if (castManager.isCasting.value) {
            castManager.getCurrentPosition()
        } else {
            controller?.currentPosition?.coerceAtLeast(0L) ?: 0L
        }
        scope.launch {
            settingsRepository.savePlaybackState(trackIds, index, position)
        }
    }

    private fun updateCurrentTrackByIndex(index: Int) {
        val queue = _queue.value
        if (index < 0 || index >= queue.size) {
            // Queue is out of sync (e.g. Android Auto started playback) — resync from player
            syncQueueFromPlayer()
            return
        }
        setCurrentTrack(queue[index])
    }

    /**
     * Rebuilds _queue from the player's current media items via Room DB lookup.
     * Called when the player has items but PlaybackManager's queue is empty/stale
     * (e.g. playback started from Android Auto or playback resumption).
     */
    private fun syncQueueFromPlayer() {
        val ctrl = controller ?: return
        val count = ctrl.mediaItemCount
        if (count == 0) return
        // Snapshot the timeline on the main thread — ids AND the metadata the service published,
        // because a track the local DB hasn't scanned yet still has to occupy its own slot here.
        // The player holds one item per queued track, so the mirror must too: a list that
        // dropped the DB misses would point at the wrong track from the first hole onward, and
        // that list is what the UI, skipToIndex and the persisted queue all read.
        val slots = (0 until count).mapNotNull { i ->
            val item = ctrl.getMediaItemAt(i)
            val raw = item.mediaId.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            val md = item.mediaMetadata
            QueueSlot(
                // Browse-tree items arrive as "track:<id>"; a placeholder built from the raw
                // string would put that prefix into Track.id and then into the persisted queue.
                id = bareTrackId(raw),
                title = md.title?.toString().orEmpty(),
                artist = md.artist?.toString().orEmpty(),
                album = md.albumTitle?.toString().orEmpty(),
                // The provider URI is content://<authority>/<coverArtId>/<size>, so the id we
                // need to store on the Track is the first path segment.
                coverArt = md.artworkUri?.pathSegments?.firstOrNull(),
            )
        }
        if (slots.isEmpty()) return
        val currentIndex = ctrl.currentMediaItemIndex
        scope.launch {
            // `scope` has no SupervisorJob, so an uncaught throw here would cancel every other
            // collector this manager owns (bitrate, server config, adaptive settings) for the
            // rest of the process.
            try {
                val resolved = libraryRepository.getTracksByIdsPadded(slots.map { it.id })
                val tracks = resolved.mapIndexed { i, track ->
                    track ?: slots[i].toPlaceholderTrack()
                }
                _queue.value = tracks
                // setCurrentTrack calls persistPlaybackState which accesses controller (main thread only)
                withContext(Dispatchers.Main) {
                    if (currentIndex in tracks.indices) {
                        setCurrentTrack(tracks[currentIndex])
                    }
                }
                DebugLog.d("Playback", "Synced queue from player: ${tracks.size} tracks, index=$currentIndex")
            } catch (e: Exception) {
                DebugLog.w("Playback", "Queue sync from player failed: ${e.message}")
            }
        }
    }

    private fun getServerConfig(): ServerConfig? {
        return cachedServerConfig
    }

    /**
     * Bitrate for URLs built *here* — Cast, playNext and addToQueue. The queue the service
     * actually plays is built by [ZonikMediaService.buildStreamUrlForTrack], which resolves
     * the same way via [isUnmeteredNetwork].
     */
    private fun getMaxBitRate(): Int {
        // Use degraded bitrate if connection is poor
        bitrateOverride?.let { return it }
        return if (context.isUnmeteredNetwork()) cachedWifiBitrate else cachedCellularBitrate
    }

    private fun degradeBitrate() {
        val current = bitrateOverride ?: getMaxBitRate()
        val currentIndex = bitrateSteps.indexOf(current)
        val nextIndex = if (currentIndex < 0) {
            // Current bitrate not in steps — find first step lower than current
            val lowerIndex = bitrateSteps.indexOfFirst { it in 1 until current }
            if (lowerIndex >= 0) lowerIndex else bitrateSteps.lastIndex
        } else {
            minOf(currentIndex + 1, bitrateSteps.lastIndex)
        }
        val newBitrate = bitrateSteps[nextIndex]
        if (newBitrate != bitrateOverride) {
            bitrateOverride = newBitrate
            stableTrackCount = 0
            DebugLog.d("Playback", "Degraded bitrate to ${newBitrate}kbps due to slow connection")
            _playbackError.value = "Slow connection — reduced to ${newBitrate}kbps"
        }
    }

    fun applyEqualizerSettings(enabled: Boolean, preset: Int, bandLevels: String?) {
        val args = android.os.Bundle().apply {
            putBoolean("eq_enabled", enabled)
            putInt("eq_preset", preset)
            if (bandLevels != null) putString("eq_band_levels", bandLevels)
        }
        // sendCustomCommand must be called on main thread
        android.os.Handler(android.os.Looper.getMainLooper()).post {
            controller?.sendCustomCommand(
                androidx.media3.session.SessionCommand("com.zonik.app.SET_EQ", android.os.Bundle.EMPTY),
                args
            )
        }
    }

    fun resetBitrate() {
        if (bitrateOverride != null) {
            DebugLog.d("Playback", "Restored original bitrate")
            bitrateOverride = null
            bufferingTimestamps.clear()
        }
    }

    private fun addToRecentlyPlayed(track: Track) {
        val current = _recentlyPlayed.value.toMutableList()
        current.removeAll { it.id == track.id }
        current.add(0, track)
        if (current.size > 20) {
            _recentlyPlayed.value = current.take(20)
        } else {
            _recentlyPlayed.value = current
        }
    }
}
