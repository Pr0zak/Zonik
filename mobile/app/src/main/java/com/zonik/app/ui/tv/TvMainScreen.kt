package com.zonik.app.ui.tv

import android.graphics.drawable.BitmapDrawable
import androidx.activity.compose.BackHandler
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.foundation.border
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Logout
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.NewReleases
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.palette.graphics.Palette
import coil.imageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.zonik.app.data.repository.LibraryRepository
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.app.media.PlaybackManager
import com.zonik.core.model.Track
import com.zonik.app.ui.components.CoverArt
import com.zonik.app.ui.theme.ZonikColors
import com.zonik.app.ui.theme.ZonikShapes
import com.zonik.app.ui.util.formatDurationMs
import com.zonik.app.ui.util.tvFocusLift
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

// ──────────────────────────────────────────────────────────────────────────────
// ViewModel
// ──────────────────────────────────────────────────────────────────────────────

@HiltViewModel
class TvViewModel @Inject constructor(
    private val playbackManager: PlaybackManager,
    private val libraryRepository: LibraryRepository,
    private val syncManager: com.zonik.app.data.repository.SyncManager,
    private val logUploader: com.zonik.app.data.api.LogUploader,
    private val updateChecker: com.zonik.app.data.api.UpdateChecker,
    private val settingsRepository: com.zonik.app.data.repository.SettingsRepository
) : ViewModel() {

    // Playback state (delegated from PlaybackManager)
    val currentTrack: StateFlow<Track?> = playbackManager.currentTrack
    val isPlaying: StateFlow<Boolean> = playbackManager.isPlaying

    // Library data. Only what the Home screen actually reads — the album/track/recent
    // feeds went with the browse tabs that were never wired up, and the recent-albums
    // collector was querying the DB on every TV launch to fill a list nothing rendered.
    val tracks: StateFlow<List<Track>> = libraryRepository.getAllTracks()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun shuffleMix() {
        viewModelScope.launch {
            try {
                val songs = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getRandomSongs(100)
                }
                if (songs.isNotEmpty()) {
                    playbackManager.playTracks(songs, endlessMix = true)
                }
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.e("TvVM", "Shuffle mix failed", e)
            }
        }
    }

    fun shuffleFavorites() {
        viewModelScope.launch {
            try {
                val starred = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getStarredTracks().shuffled().take(100)
                }
                if (starred.isNotEmpty()) {
                    playbackManager.playTracks(starred)
                }
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.e("TvVM", "Shuffle favorites failed", e)
            }
        }
    }

    fun shuffleRecentlyAdded() {
        viewModelScope.launch {
            try {
                val tracks = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getRecentlyAddedTracks(100).shuffled()
                }
                if (tracks.isNotEmpty()) playbackManager.playTracks(tracks)
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.e("TvVM", "Shuffle recently-added failed", e)
            }
        }
    }

    fun shuffleNewestByYear() {
        viewModelScope.launch {
            try {
                val tracks = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getNewestByYearTracks(100).shuffled()
                }
                if (tracks.isNotEmpty()) playbackManager.playTracks(tracks)
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.e("TvVM", "Shuffle newest-by-year failed", e)
            }
        }
    }

    fun playTrack(track: Track) {
        val allTracks = tracks.value
        val index = allTracks.indexOfFirst { it.id == track.id }
        if (index >= 0) {
            playbackManager.playTracks(allTracks, index)
        } else {
            playbackManager.playTracks(listOf(track))
        }
    }

    fun playAlbum(albumId: String) {
        viewModelScope.launch {
            try {
                val (_, albumTracks) = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getAlbumDetail(albumId)
                }
                if (albumTracks.isNotEmpty()) {
                    playbackManager.playTracks(albumTracks)
                }
            } catch (_: Exception) {}
        }
    }

    // ── Browse rails (the Stage's DOWN panel) ─────────────────────────────────────

    /** The play queue, for the Stage's "Up next" line. */
    val queue: StateFlow<List<Track>> = playbackManager.queue

    /** Newest albums in the local library; no network needed. */
    val recentAlbums: StateFlow<List<com.zonik.core.model.Album>> = libraryRepository.getRecentAlbums(20)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val _recentlyPlayedAlbums = MutableStateFlow<List<com.zonik.core.model.Album>>(emptyList())
    val recentlyPlayedAlbums: StateFlow<List<com.zonik.core.model.Album>> = _recentlyPlayedAlbums.asStateFlow()

    private val _playlists = MutableStateFlow<List<com.zonik.core.model.Playlist>>(emptyList())
    val playlists: StateFlow<List<com.zonik.core.model.Playlist>> = _playlists.asStateFlow()

    /** Refreshes the rails that come from the server. Called each time browse opens. */
    fun loadBrowse() {
        viewModelScope.launch {
            try {
                val (recent, lists) = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getRecentlyPlayedAlbums(20) to libraryRepository.getPlaylists()
                }
                _recentlyPlayedAlbums.value = recent
                _playlists.value = lists
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.w("TvVM", "Browse rails failed: ${e.message}")
            }
        }
    }

    fun playPlaylist(playlistId: String) {
        viewModelScope.launch {
            try {
                val tracks = kotlinx.coroutines.withContext(Dispatchers.IO) {
                    libraryRepository.getPlaylistTracks(playlistId)
                }
                if (tracks.isNotEmpty()) playbackManager.playTracks(tracks)
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.e("TvVM", "Play playlist failed", e)
            }
        }
    }

    fun togglePlayPause() = playbackManager.togglePlayPause()
    fun skipNext() = playbackManager.skipNext()
    fun skipPrevious() = playbackManager.skipPrevious()
    fun getCurrentPosition(): Long = playbackManager.getCurrentPosition()
    fun getDuration(): Long = playbackManager.getDuration()

    private val _isStarred = MutableStateFlow(false)
    val isStarred: StateFlow<Boolean> = _isStarred.asStateFlow()

    fun refreshStarred() {
        val track = currentTrack.value ?: return
        _isStarred.value = track.starred
    }

    // ── Ambient visualizer ────────────────────────────────────────────────────────
    // Restored after Phase 1 deleted it. What made the old one hostile was the container
    // around it — it unmounted the screen and ate D-pad keys — not the visuals, so the
    // renderer comes back as it was and the container is rebuilt in TvMainScreen.

    val ambientEnabled: StateFlow<Boolean> = settingsRepository.tvAmbientEnabled
        .stateIn(viewModelScope, SharingStarted.Eagerly, true)
    val ambientDelaySec: StateFlow<Int> = settingsRepository.tvAmbientDelaySec
        .stateIn(viewModelScope, SharingStarted.Eagerly, 10)
    val ambientBeatReactive: StateFlow<Boolean> = settingsRepository.tvAmbientBeatReactive
        .stateIn(viewModelScope, SharingStarted.Eagerly, true)

    fun setAmbientEnabled(enabled: Boolean) {
        viewModelScope.launch { settingsRepository.setTvAmbientEnabled(enabled) }
    }

    fun setAmbientDelaySec(seconds: Int) {
        viewModelScope.launch { settingsRepository.setTvAmbientDelaySec(seconds) }
    }

    fun setAmbientBeatReactive(enabled: Boolean) {
        viewModelScope.launch { settingsRepository.setTvAmbientBeatReactive(enabled) }
    }

    /** Effects in the rotation, in the order they rotate. Never empty. */
    val ambientEffects: StateFlow<List<DemoEffect>> = settingsRepository.tvAmbientEffectsOff
        .map { off -> DemoEffect.entries.filter { it.name !in off }.ifEmpty { DemoEffect.entries } }
        .stateIn(viewModelScope, SharingStarted.Eagerly, DemoEffect.entries)

    /** Adds or removes one effect; the last one left cannot be removed. */
    fun toggleAmbientEffect(effect: DemoEffect) {
        val current = ambientEffects.value.toSet()
        val next = if (effect in current) current - effect else current + effect
        if (next.isEmpty()) return
        setAmbientEffects(next)
    }

    fun setAmbientEffects(effects: Set<DemoEffect>) {
        if (effects.isEmpty()) return
        viewModelScope.launch {
            settingsRepository.setTvAmbientEffectsOff(
                DemoEffect.entries.filter { it !in effects }.map { it.name }.toSet()
            )
        }
    }

    val ambientRotateSec: StateFlow<Int> = settingsRepository.tvAmbientRotateSec
        .stateIn(viewModelScope, SharingStarted.Eagerly, 60)

    fun setAmbientRotateSec(seconds: Int) {
        viewModelScope.launch { settingsRepository.setTvAmbientRotateSec(seconds) }
    }

    val ambientInfo: StateFlow<String> = settingsRepository.tvAmbientInfo
        .stateIn(viewModelScope, SharingStarted.Eagerly, "FADE")

    fun setAmbientInfo(mode: String) {
        viewModelScope.launch { settingsRepository.setTvAmbientInfo(mode) }
    }

    val ambientTransition: StateFlow<Int> = settingsRepository.tvAmbientTransition
        .stateIn(viewModelScope, SharingStarted.Eagerly, -1)

    fun setAmbientTransition(kind: Int) {
        viewModelScope.launch { settingsRepository.setTvAmbientTransition(kind) }
    }

    val ambientTransitionMs: StateFlow<Int> = settingsRepository.tvAmbientTransitionMs
        .stateIn(viewModelScope, SharingStarted.Eagerly, 1600)

    fun setAmbientTransitionMs(ms: Int) {
        viewModelScope.launch { settingsRepository.setTvAmbientTransitionMs(ms) }
    }

    val ambientTrails: StateFlow<Boolean> = settingsRepository.tvAmbientTrails
        .stateIn(viewModelScope, SharingStarted.Eagerly, false)

    fun setAmbientTrails(enabled: Boolean) {
        viewModelScope.launch { settingsRepository.setTvAmbientTrails(enabled) }
    }

    private val _pulse = MutableStateFlow(AmbientPulse())
    val pulse: StateFlow<AmbientPulse> = _pulse.asStateFlow()

    /** Server-analysed tempo for the current track, or 0 when it has none. */
    private val _trackBpm = MutableStateFlow(0f)
    val trackBpm: StateFlow<Float> = _trackBpm.asStateFlow()

    private var visualizer: android.media.audiofx.Visualizer? = null
    private var analyzer: PulseAnalyzer? = null

    init {
        // The beat grid needs the server's tempo, which is stored per track and costs one small
        // request. Fetched on every track change so the clock is ready before the visuals are.
        viewModelScope.launch {
            currentTrack.collect { track ->
                _trackBpm.value = 0f
                val id = track?.id ?: return@collect
                _trackBpm.value = try {
                    kotlinx.coroutines.withContext(Dispatchers.IO) {
                        libraryRepository.getTrackTempo(id) ?: 0f
                    }
                } catch (e: Exception) {
                    com.zonik.app.data.DebugLog.w("TvVM", "No tempo for $id: ${e.message}")
                    0f
                }
            }
        }
    }

    /**
     * Taps the output mix for an FFT so the visuals can move with the music. Verified working on
     * a Chromecast with Google TV. Needs RECORD_AUDIO; when that is missing, or the device
     * refuses the capture, the visuals fall back to the tempo grid alone.
     */
    fun startVisualizer() {
        if (visualizer != null) return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // The session id is not valid until the player has actually started.
                kotlinx.coroutines.delay(1500)
                val sessionId = com.zonik.app.media.ZonikMediaService.currentAudioSessionId
                if (sessionId == 0) {
                    com.zonik.app.data.DebugLog.w("TvVM", "Visualizer: no audio session; grid only")
                    return@launch
                }
                val viz = android.media.audiofx.Visualizer(sessionId)
                // Ask for the largest capture the device allows. At the old 128 points a bin was
                // 344 Hz wide, so "bass" actually meant vocals and guitars and the kick fell in a
                // bin that was skipped entirely.
                viz.captureSize = android.media.audiofx.Visualizer.getCaptureSizeRange()[1]
                val pulseAnalyzer = PulseAnalyzer(viz.samplingRate / 1000)
                analyzer = pulseAnalyzer
                viz.setDataCaptureListener(
                    object : android.media.audiofx.Visualizer.OnDataCaptureListener {
                        // Both arrive on the capture thread, waveform first; the waveform is held
                        // and rides along with the next FFT pulse.
                        override fun onWaveFormDataCapture(
                            v: android.media.audiofx.Visualizer?, waveform: ByteArray?, rate: Int
                        ) {
                            waveform ?: return
                            latestWave = downsampleWave(waveform)
                        }

                        override fun onFftDataCapture(
                            v: android.media.audiofx.Visualizer?, fft: ByteArray?, rate: Int
                        ) {
                            fft ?: return
                            _pulse.value = pulseAnalyzer.process(fft).copy(waveform = latestWave)
                        }
                    },
                    // Full rate, not half: the old setting analysed one 3 ms window in every
                    // 100 ms and missed most of what it was meant to be watching.
                    android.media.audiofx.Visualizer.getMaxCaptureRate(),
                    true,
                    true
                )
                viz.enabled = true
                visualizer = viz
                com.zonik.app.data.DebugLog.d(
                    "TvVM",
                    "Visualizer started (session=$sessionId, capture=${viz.captureSize}, rate=${viz.samplingRate}Hz)"
                )
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.w("TvVM", "Visualizer unavailable: ${e.message}")
            }
        }
    }

    @Volatile private var latestWave: FloatArray? = null

    /** 8-bit unsigned PCM (128 = silence) averaged down to [WAVEFORM_POINTS] values in 0..1. */
    private fun downsampleWave(pcm: ByteArray): FloatArray {
        val out = FloatArray(WAVEFORM_POINTS)
        val per = maxOf(1, pcm.size / WAVEFORM_POINTS)
        for (i in 0 until WAVEFORM_POINTS) {
            var sum = 0
            val start = i * per
            val end = minOf(pcm.size, start + per)
            for (j in start until end) sum += pcm[j].toInt() and 0xFF
            out[i] = if (end > start) sum / (end - start) / 255f else 0.5f
        }
        return out
    }

    fun stopVisualizer() {
        try {
            visualizer?.release()
        } catch (_: Exception) {
        }
        visualizer = null
        analyzer?.reset()
        analyzer = null
        latestWave = null
        _pulse.value = AmbientPulse()
    }

    override fun onCleared() {
        super.onCleared()
        stopVisualizer()
    }

    fun toggleStar() {
        val track = currentTrack.value ?: return
        viewModelScope.launch {
            kotlinx.coroutines.withContext(Dispatchers.IO) {
                if (_isStarred.value) {
                    libraryRepository.unstar(track.id)
                } else {
                    libraryRepository.star(track.id)
                }
            }
            _isStarred.value = !_isStarred.value
        }
    }

    val syncState = syncManager.syncState

    fun syncNow() {
        viewModelScope.launch { syncManager.fullSync() }
    }

    private val _logUploadResult = MutableStateFlow<String?>(null)
    val logUploadResult: StateFlow<String?> = _logUploadResult.asStateFlow()

    fun uploadLogs() {
        viewModelScope.launch {
            _logUploadResult.value = "Uploading..."
            val id = logUploader.uploadLogsToServer()
            _logUploadResult.value = if (id != null) "Uploaded (ID: $id)" else "Upload failed"
        }
    }

    private val _updateStatus = MutableStateFlow<String?>(null)
    val updateStatus: StateFlow<String?> = _updateStatus.asStateFlow()

    private val _updateProgress = MutableStateFlow<Float?>(null)
    val updateProgress: StateFlow<Float?> = _updateProgress.asStateFlow()

    fun checkForUpdate() {
        viewModelScope.launch {
            _updateStatus.value = "Checking..."
            try {
                val update = updateChecker.checkForUpdate()
                if (update != null) {
                    _updateStatus.value = "Downloading v${update.version}..."
                    val success = updateChecker.downloadAndInstall(update) { progress ->
                        _updateProgress.value = progress
                    }
                    _updateStatus.value = if (success) "Installing..." else "Download failed"
                    _updateProgress.value = null
                } else {
                    _updateStatus.value = "Up to date"
                }
            } catch (e: Exception) {
                _updateStatus.value = "Failed: ${e.message?.take(30)}"
            }
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Tab definitions
// ──────────────────────────────────────────────────────────────────────────────


// ──────────────────────────────────────────────────────────────────────────────
// Colors
// ──────────────────────────────────────────────────────────────────────────────

private val TvBackground = Color(0xFF151320)
private val TvCardBackground = Color(0xFF1E1C2A)

/** How long the cover and title stay over the visuals in "Show, then fade" mode. */
private const val INFO_VISIBLE_MS = 10_000L

// ──────────────────────────────────────────────────────────────────────────────
// Main Screen
// ──────────────────────────────────────────────────────────────────────────────

@Composable
fun TvMainScreen(
    onDisconnected: () -> Unit = {},
    viewModel: TvViewModel = hiltViewModel()
) {
    val currentTrack by viewModel.currentTrack.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()

    // The Stage is the root; Settings replaces it full-screen. `panel` is what sits over the
    // Stage (the UP strip or the DOWN rails) and lives here so BACK and the ambient timer can
    // see it.
    var showSettings by remember { mutableStateOf(false) }
    var panel by remember { mutableStateOf(StagePanel.NONE) }

    // ── Ambient visualizer state ─────────────────────────────────────────────────
    val ambientEnabled by viewModel.ambientEnabled.collectAsState()
    val ambientDelaySec by viewModel.ambientDelaySec.collectAsState()
    var ambientActive by remember { mutableStateOf(false) }
    var lastInteraction by remember { mutableLongStateOf(0L) }

    // Arms only while something is playing and the bare Stage is up — nobody wants the screen
    // taken over mid-way through changing a setting or picking an album. A delay of 0 means
    // on-demand only.
    LaunchedEffect(lastInteraction, isPlaying, showSettings, panel, ambientEnabled, ambientDelaySec) {
        if (!ambientEnabled || ambientDelaySec <= 0) return@LaunchedEffect
        if (!isPlaying || showSettings || panel != StagePanel.NONE || ambientActive) return@LaunchedEffect
        delay(ambientDelaySec * 1000L)
        ambientActive = true
    }

    // With nothing playing the rails ARE the screen, so BACK leaves the app from there rather
    // than closing them onto an empty Stage.
    val railsAreHome = currentTrack == null && panel == StagePanel.BROWSE
    BackHandler(enabled = ambientActive || showSettings || (panel != StagePanel.NONE && !railsAreHome)) {
        when {
            ambientActive -> {
                ambientActive = false
                lastInteraction = System.currentTimeMillis()
            }
            showSettings -> showSettings = false
            else -> panel = StagePanel.NONE
        }
    }

    // Ambient background tint pulled from the current album art.
    var ambientDominant by remember { mutableStateOf(TvBackground) }
    val animatedBg by animateColorAsState(ambientDominant, tween(1200), label = "bg")
    val paletteCtx = LocalContext.current
    LaunchedEffect(currentTrack?.coverArt) {
        val coverArtId = currentTrack?.coverArt ?: return@LaunchedEffect
        // Palette quantizes the whole bitmap synchronously, and a LaunchedEffect body runs on
        // the composition's dispatcher — i.e. the main thread, which on a TV box is also the
        // thread the media session dispatches commands on. Pressing play sets the current track
        // first, so this used to fire and stall the very frame the user was waiting for.
        val tint = kotlinx.coroutines.withContext(Dispatchers.IO) {
            try {
                val request = ImageRequest.Builder(paletteCtx)
                    .data("http://localhost/rest/getCoverArt.view?id=$coverArtId&size=300")
                    .allowHardware(false)
                    .build()
                val result = paletteCtx.imageLoader.execute(request)
                val bitmap = ((result as? SuccessResult)?.drawable as? BitmapDrawable)?.bitmap
                    ?: return@withContext null
                Color(Palette.from(bitmap).generate().getDarkMutedColor(0xFF151320.toInt()))
            } catch (_: Exception) {
                null
            }
        }
        if (tint != null) ambientDominant = tint
    }

    // Hoisted out of the modifier chain: an inline Brush would be a fresh instance
    // (and a cold shader cache) on every recomposition, and D-pad key repeat
    // recomposes this screen ~25 times a second.
    val background = remember(animatedBg, currentTrack != null) {
        if (currentTrack != null) Brush.radialGradient(listOf(animatedBg.copy(alpha = 0.6f), TvBackground))
        else Brush.verticalGradient(listOf(TvBackground, TvBackground))
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(background)
            .onPreviewKeyEvent { keyEvent ->
                // Transport keys only. Every D-pad key must fall through to Compose's
                // focus system, and a held key must act once rather than ~25 times.
                if (keyEvent.nativeKeyEvent.action != android.view.KeyEvent.ACTION_DOWN) return@onPreviewKeyEvent false
                lastInteraction = System.currentTimeMillis()
                // Leaving ambient consumes the key that dismissed it, so the press that wakes
                // the screen does not also fire whatever button happened to be focused behind
                // it. Transport keys are the exception: they act and the visuals stay up, which
                // is the whole point of having a now-playing screen.
                if (ambientActive) {
                    // The visualizer is a now-playing screen, so it owns the transport while it
                    // is up. Most TV remotes have no dedicated skip buttons — people press the
                    // D-pad — so LEFT/RIGHT/OK have to drive playback here rather than mean
                    // "leave", which is what the screensaver this replaced did too.
                    when (keyEvent.nativeKeyEvent.keyCode) {
                        android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                        android.view.KeyEvent.KEYCODE_MEDIA_PLAY,
                        android.view.KeyEvent.KEYCODE_MEDIA_PAUSE,
                        android.view.KeyEvent.KEYCODE_MEDIA_NEXT,
                        android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS ->
                            Unit // handled by the transport block below; stay in ambient

                        android.view.KeyEvent.KEYCODE_DPAD_RIGHT -> {
                            viewModel.skipNext()
                            return@onPreviewKeyEvent true
                        }
                        android.view.KeyEvent.KEYCODE_DPAD_LEFT -> {
                            viewModel.skipPrevious()
                            return@onPreviewKeyEvent true
                        }
                        android.view.KeyEvent.KEYCODE_DPAD_CENTER,
                        android.view.KeyEvent.KEYCODE_ENTER,
                        android.view.KeyEvent.KEYCODE_NUMPAD_ENTER,
                        android.view.KeyEvent.KEYCODE_BUTTON_SELECT -> {
                            viewModel.togglePlayPause()
                            return@onPreviewKeyEvent true
                        }

                        // Volume and mute belong to the system and say nothing about wanting
                        // to leave. Falling into the branch below would have swallowed them —
                        // dismissing the visuals AND eating the keypress, so the volume would
                        // not even change. Hand them straight back untouched.
                        android.view.KeyEvent.KEYCODE_VOLUME_UP,
                        android.view.KeyEvent.KEYCODE_VOLUME_DOWN,
                        android.view.KeyEvent.KEYCODE_VOLUME_MUTE ->
                            return@onPreviewKeyEvent false

                        // Anything else means "get me out of here" — UP, DOWN, BACK and the
                        // rest. The key is consumed so waking the screen does not also fire
                        // whatever button sat behind it.
                        else -> {
                            ambientActive = false
                            return@onPreviewKeyEvent true
                        }
                    }
                }
                if (keyEvent.nativeKeyEvent.repeatCount != 0) {
                    return@onPreviewKeyEvent when (keyEvent.nativeKeyEvent.keyCode) {
                        android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                        android.view.KeyEvent.KEYCODE_MEDIA_PLAY,
                        android.view.KeyEvent.KEYCODE_MEDIA_PAUSE,
                        android.view.KeyEvent.KEYCODE_MEDIA_NEXT,
                        android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS -> true
                        else -> false
                    }
                }
                when (keyEvent.nativeKeyEvent.keyCode) {
                    android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> { viewModel.togglePlayPause(); true }
                    android.view.KeyEvent.KEYCODE_MEDIA_PLAY -> { if (!isPlaying) viewModel.togglePlayPause(); true }
                    android.view.KeyEvent.KEYCODE_MEDIA_PAUSE -> { if (isPlaying) viewModel.togglePlayPause(); true }
                    android.view.KeyEvent.KEYCODE_MEDIA_NEXT -> { viewModel.skipNext(); true }
                    android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS -> { viewModel.skipPrevious(); true }
                    else -> false
                }
            }
    ) {
        // 48dp/27dp is the 5% overscan margin every TV panel is allowed to eat.
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 48.dp, vertical = 27.dp)
        ) {
            if (showSettings) {
                TvSettingsContent(viewModel = viewModel, onDisconnected = onDisconnected)
            } else {
                TvStage(
                    viewModel = viewModel,
                    panel = panel,
                    onPanelChange = { panel = it },
                    onEnterAmbient = { ambientActive = true },
                    onOpenSettings = {
                        panel = StagePanel.NONE
                        showSettings = true
                    },
                )
            }
        }

        // Drawn OVER the screen rather than instead of it. The old screensaver swapped the
        // content tree out, which is what cost every bit of D-pad state and made the remote
        // feel dead on the way back; this leaves focus exactly where the user left it.
        val track = currentTrack
        if (ambientActive && track != null) {
            TvAmbientOverlay(
                viewModel = viewModel,
                track = track,
                isPlaying = isPlaying,
                lastKeyAt = lastInteraction
            )
        }
    }
}

/**
 * The ambient / visualizer screen. Beat reactivity comes from the output-mix FFT when
 * RECORD_AUDIO has been granted; without it the effect keeps time from the server's tempo and
 * everything else still works, so the permission is asked for once and never insisted upon.
 */
@Composable
private fun TvAmbientOverlay(
    viewModel: TvViewModel,
    track: Track,
    isPlaying: Boolean,
    lastKeyAt: Long,
) {
    val bpm by viewModel.trackBpm.collectAsState()
    AudioCaptureEffect(viewModel)

    var positionMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(0L) }
    LaunchedEffect(track, isPlaying) {
        while (true) {
            positionMs = viewModel.getCurrentPosition()
            durationMs = viewModel.getDuration()
            delay(1000L)
        }
    }

    // Rotation: a new effect on every track change and, if set, on a timer within the track
    // (restarted by each track change). The order is a shuffled deck: every enabled effect
    // plays once before any repeats, and a fresh shuffle never opens on the one just shown.
    // The renderer holds each switch for the next kick.
    val enabled by viewModel.ambientEffects.collectAsState()
    val rotateSec by viewModel.ambientRotateSec.collectAsState()
    val transition by viewModel.ambientTransition.collectAsState()
    val transitionMs by viewModel.ambientTransitionMs.collectAsState()
    val trails by viewModel.ambientTrails.collectAsState()
    var deck by remember(enabled) { mutableStateOf(enabled.shuffled()) }
    var deckIndex by remember(enabled) { mutableIntStateOf(0) }
    fun advanceDeck() {
        if (deckIndex + 1 < deck.size) {
            deckIndex++
        } else {
            val last = deck[deckIndex]
            var next = enabled.shuffled()
            if (next.size > 1 && next.first() == last) next = next.drop(1) + next.first()
            deck = next
            deckIndex = 0
        }
    }
    LaunchedEffect(track.id) { advanceDeck() }
    LaunchedEffect(track.id, rotateSec) {
        if (rotateSec <= 0) return@LaunchedEffect
        while (true) {
            delay(rotateSec * 1000L)
            advanceDeck()
        }
    }
    val effect = deck.getOrElse(deckIndex) { enabled.first() }

    // Cover and title: always, never, or shown on each track change and remote press, then
    // faded so the effect gets the whole screen.
    val infoMode by viewModel.ambientInfo.collectAsState()
    var infoVisible by remember { mutableStateOf(true) }
    LaunchedEffect(track.id, lastKeyAt, infoMode) {
        infoVisible = infoMode != "NEVER"
        if (infoMode == "FADE") {
            delay(INFO_VISIBLE_MS)
            infoVisible = false
        }
    }
    val infoAlpha by animateFloatAsState(if (infoVisible) 1f else 0f, tween(1200), label = "info")

    // The beat grid, from the server's stored tempo. The visualizer aligns its phase to the
    // onsets it hears and uses it to swell into each beat rather than trailing it.
    val beatClock = remember(track.id, bpm) { BeatClock(bpm) }
    val art = rememberAmbientArt(track.coverArt)

    // No background on this Box: the GL surface sits behind the window and shows through a
    // hole in it, so anything opaque drawn here would cover the effect.
    Box(modifier = Modifier.fillMaxSize()) {
        DemoVisualizer(
            effect = effect,
            pulse = viewModel.pulse,
            beatClock = beatClock,
            cover = art.cover,
            palette = art.palette,
            transition = transition,
            transitionMs = transitionMs,
            title = "${track.title}  ·  ${track.artist}",
            trails = trails,
            modifier = Modifier.fillMaxSize()
        )
        // Keeps the type legible without burying the effect: darkness where the words are.
        // Alpha is read in the layer block, so the fade redraws without recomposing.
        Box(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer { alpha = infoAlpha }
                .background(
                    Brush.verticalGradient(
                        listOf(Color(0x66000000), Color(0x00000000), Color(0xCC0A0810))
                    )
                )
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer { alpha = infoAlpha }
                .padding(horizontal = 48.dp, vertical = 27.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            // An effect that frames the cover draws it at the centre itself, so the words move
            // to the bottom out of its way instead of stacking a second cover over the first.
            verticalArrangement = if (effect.framesCover) Arrangement.Bottom else Arrangement.Center
        ) {
            if (!effect.framesCover) {
                CoverArt(
                    coverArtId = track.coverArt,
                    contentDescription = track.title,
                    modifier = Modifier
                        .size(320.dp)
                        .clip(ZonikShapes.coverArtLargeShape),
                    size = 600
                )
                Spacer(modifier = Modifier.height(32.dp))
            }
            Text(
                text = track.title,
                style = MaterialTheme.typography.headlineLarge,
                color = Color.White,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = track.artist,
                style = MaterialTheme.typography.titleLarge,
                color = Color.White.copy(alpha = 0.7f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(modifier = Modifier.height(28.dp))
            val progress = if (durationMs > 0) (positionMs.toFloat() / durationMs) else 0f
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth(0.5f)
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = ZonikColors.gold,
                trackColor = Color.White.copy(alpha = 0.1f)
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(0.5f),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = formatDurationMs(positionMs),
                    style = MaterialTheme.typography.labelMedium,
                    color = Color.White.copy(alpha = 0.5f)
                )
                Text(
                    text = if (durationMs > 0) formatDurationMs(durationMs) else "--:--",
                    style = MaterialTheme.typography.labelMedium,
                    color = Color.White.copy(alpha = 0.5f)
                )
            }
        }
    }
}



@Composable
private fun TvSettingsContent(
    viewModel: TvViewModel,
    onDisconnected: () -> Unit
) {
    // The visualizer page replaces the list rather than stacking over it; returning puts focus
    // back on the row that opened it instead of dropping it at the top of the list.
    var showVisualizer by remember { mutableStateOf(false) }
    var returnFocus by remember { mutableStateOf(false) }
    val visualizerRow = remember { FocusRequester() }
    if (showVisualizer) {
        TvVisualizerSettings(viewModel = viewModel, onBack = {
            showVisualizer = false
            returnFocus = true
        })
        return
    }
    // Settings opens from the Stage's strip, whose button is gone the moment this replaces it,
    // so focus has to be put somewhere on purpose: the first row on the way in, the Visualizer
    // row on the way back from its page.
    val firstRow = remember { FocusRequester() }
    // Keyed to the list appearing, not to the flag: clearing the flag below must not restart
    // this and send focus back to the first row.
    LaunchedEffect(Unit) {
        val target = if (returnFocus) visualizerRow else firstRow
        for (attempt in 0 until 5) {
            androidx.compose.runtime.withFrameNanos { }
            if (runCatching { target.requestFocus() }.isSuccess) break
        }
        returnFocus = false
    }
    val onOpenVisualizer = { showVisualizer = true }
    val context = androidx.compose.ui.platform.LocalContext.current
    val syncState by viewModel.syncState.collectAsState()
    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            // Inside the scroll, which clips to its own bounds: room for the focused row's lift
            // and glow on every side, or it is cut off at the edges.
            .padding(horizontal = 24.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            text = "Settings",
            style = MaterialTheme.typography.headlineMedium,
            color = Color.White,
            fontWeight = FontWeight.Bold
        )
        Spacer(modifier = Modifier.height(16.dp))

        // Sync
        TvSettingsButton(
            modifier = Modifier.focusRequester(firstRow),
            icon = Icons.Default.Sync,
            title = if (syncState.isSyncing) "Syncing..." else "Sync Library",
            subtitle = when {
                syncState.isSyncing -> syncState.phase.ifEmpty { "Starting..." }
                syncState.lastSyncResult != null -> syncState.lastSyncResult!!
                else -> "Sync tracks, albums, and artists from server"
            },
            // No `enabled` guard: SyncManager.fullSync() already claims the sync slot atomically
            // and returns early for a second caller, so a repeat press is a no-op anyway.
            onClick = { viewModel.syncNow() },
            isLoading = syncState.isSyncing
        )

        // Visualizer — its own page, with a live preview and the effect gallery.
        val ambientOn by viewModel.ambientEnabled.collectAsState()
        val effectCount by viewModel.ambientEffects.collectAsState()
        TvSettingsButton(
            icon = Icons.Default.GraphicEq,
            title = "Visualizer",
            subtitle = if (ambientOn) "On · ${effectCount.size} effects in rotation — press OK to set up"
                       else "Off — press OK to set up",
            onClick = onOpenVisualizer,
            modifier = Modifier.focusRequester(visualizerRow)
        )

        // Upload Logs
        val logResult by viewModel.logUploadResult.collectAsState()
        TvSettingsButton(
            icon = Icons.Default.Upload,
            title = "Upload Logs",
            subtitle = logResult ?: "Send debug logs to server for troubleshooting",
            onClick = { viewModel.uploadLogs() },
            isLoading = logResult == "Uploading..."
        )

        // Check Update
        val updateStatus by viewModel.updateStatus.collectAsState()
        val updateProgress by viewModel.updateProgress.collectAsState()
        TvSettingsButton(
            icon = Icons.Default.SystemUpdate,
            title = "Check for Update",
            subtitle = updateStatus ?: "Download and install latest version",
            onClick = { viewModel.checkForUpdate() },
            isLoading = updateStatus == "Checking..." || updateProgress != null
        )

        // Disconnect
        TvSettingsButton(
            icon = Icons.Default.Logout,
            title = "Disconnect",
            subtitle = "Log out from server",
            onClick = onDisconnected,
            tint = MaterialTheme.colorScheme.error
        )

        Spacer(modifier = Modifier.height(80.dp))
    }
}

@Composable
private fun TvSettingsButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit,
    isLoading: Boolean = false,
    tint: Color = Color.White,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            // Lift before background: the glow's shadow must sit under the row, not over it.
            .tvFocusLift(ZonikShapes.cardShape, scale = 1.02f)
            .background(TvCardBackground, ZonikShapes.cardShape)
            // Never gate this with `clickable(enabled = …)`. Compose undelegates the clickable's
            // focus target when enabled flips false, and detaching the *focused* node clears
            // focus all the way to the root — so a row that disables itself on click takes the
            // remote with it: highlight gone, D-pad position lost, and the root key handler
            // silenced (key events only travel the active node's own ancestor chain).
            .clickable(onClick = onClick)
            .padding(20.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (isLoading) {
            CircularProgressIndicator(
                modifier = Modifier.size(24.dp),
                strokeWidth = 2.dp,
                color = ZonikColors.gold
            )
        } else {
            Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(24.dp))
        }
        Spacer(modifier = Modifier.width(16.dp))
        Column {
            Text(title, style = MaterialTheme.typography.titleMedium, color = tint)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Color.White.copy(alpha = 0.5f))
        }
    }
}

