package com.zonik.app.ui.tv

import android.graphics.drawable.BitmapDrawable
import androidx.activity.compose.BackHandler
import androidx.compose.animation.animateColorAsState
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
import com.zonik.app.media.PlaybackManager
import com.zonik.core.model.Track
import com.zonik.app.ui.components.CoverArt
import com.zonik.app.ui.theme.ZonikColors
import com.zonik.app.ui.theme.ZonikShapes
import com.zonik.app.ui.util.formatDurationMs
import com.zonik.app.ui.util.tvFocusHighlight
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
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
                    playbackManager.playTracks(songs)
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

    private val _bassLevel = MutableStateFlow(0f)
    val bassLevel: StateFlow<Float> = _bassLevel.asStateFlow()
    private val _fftMagnitudes = MutableStateFlow(FloatArray(32))
    val fftMagnitudes: StateFlow<FloatArray> = _fftMagnitudes.asStateFlow()
    private var visualizer: android.media.audiofx.Visualizer? = null

    /**
     * Taps the output mix for an FFT so the visuals can move with the music. Verified working
     * on a Chromecast with Google TV. Needs RECORD_AUDIO; when that is missing or the device
     * refuses the capture, the particles simply drift instead.
     */
    fun startVisualizer() {
        if (visualizer != null) return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                // The session id is not valid until the player has actually started.
                kotlinx.coroutines.delay(1500)
                val sessionId = com.zonik.app.media.ZonikMediaService.currentAudioSessionId
                com.zonik.app.data.DebugLog.d("TvVM", "Visualizer: audio session $sessionId")
                if (sessionId == 0) {
                    com.zonik.app.data.DebugLog.w("TvVM", "Visualizer: no audio session, drifting only")
                    return@launch
                }
                val viz = android.media.audiofx.Visualizer(sessionId)
                viz.captureSize = 128
                viz.setDataCaptureListener(
                    object : android.media.audiofx.Visualizer.OnDataCaptureListener {
                        override fun onWaveFormDataCapture(
                            v: android.media.audiofx.Visualizer?, waveform: ByteArray?, rate: Int
                        ) {}

                        override fun onFftDataCapture(
                            v: android.media.audiofx.Visualizer?, fft: ByteArray?, rate: Int
                        ) {
                            fft ?: return
                            val n = fft.size / 2
                            var bass = 0f
                            for (i in 1..4) {
                                val re = fft[2 * i].toFloat()
                                val im = if (2 * i + 1 < fft.size) fft[2 * i + 1].toFloat() else 0f
                                bass += kotlin.math.sqrt(re * re + im * im)
                            }
                            var highs = 0f
                            for (i in (n * 2 / 3)..(n - 1).coerceAtLeast(1)) {
                                val re = fft[2 * i].toFloat()
                                val im = if (2 * i + 1 < fft.size) fft[2 * i + 1].toFloat() else 0f
                                highs += kotlin.math.sqrt(re * re + im * im)
                            }
                            _bassLevel.value = (bass / 400f + highs / 600f).coerceIn(0f, 1f)
                            val mags = FloatArray(32)
                            for (bin in 0 until 32) {
                                val idx = 1 + bin * (n - 1) / 32
                                val re = fft[2 * idx].toFloat()
                                val im = if (2 * idx + 1 < fft.size) fft[2 * idx + 1].toFloat() else 0f
                                mags[bin] = (kotlin.math.sqrt(re * re + im * im) / 128f).coerceIn(0f, 1f)
                            }
                            _fftMagnitudes.value = mags
                        }
                    },
                    android.media.audiofx.Visualizer.getMaxCaptureRate() / 2,
                    false,
                    true
                )
                viz.enabled = true
                visualizer = viz
                com.zonik.app.data.DebugLog.d("TvVM", "Visualizer started (session=$sessionId)")
            } catch (e: Exception) {
                com.zonik.app.data.DebugLog.w("TvVM", "Visualizer unavailable: ${e.message}")
            }
        }
    }

    fun stopVisualizer() {
        try {
            visualizer?.release()
        } catch (_: Exception) {
        }
        visualizer = null
        _bassLevel.value = 0f
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

private enum class TvTab(val label: String) {
    HOME("Home"),
    SETTINGS("Settings")
}

// ──────────────────────────────────────────────────────────────────────────────
// Colors
// ──────────────────────────────────────────────────────────────────────────────

private val TvBackground = Color(0xFF151320)
private val TvCardBackground = Color(0xFF1E1C2A)

// ──────────────────────────────────────────────────────────────────────────────
// Main Screen
// ──────────────────────────────────────────────────────────────────────────────

@Composable
fun TvMainScreen(
    onNavigateToAlbum: (String) -> Unit = {},
    onDisconnected: () -> Unit = {},
    viewModel: TvViewModel = hiltViewModel()
) {
    val currentTrack by viewModel.currentTrack.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()

    var selectedTab by remember { mutableStateOf(TvTab.HOME) }
    // One-shot, hoisted above the tab swap: `when (selectedTab)` tears TvHomeContent down and
    // rebuilds it, so an effect living inside it re-fires on every return to Home and yanks
    // focus off the sidebar item the user just pressed.
    var homeFocusClaimed by remember { mutableStateOf(false) }

    // ── Ambient visualizer state ─────────────────────────────────────────────────
    val ambientEnabled by viewModel.ambientEnabled.collectAsState()
    val ambientDelaySec by viewModel.ambientDelaySec.collectAsState()
    var ambientActive by remember { mutableStateOf(false) }
    var lastInteraction by remember { mutableLongStateOf(0L) }

    // Arms only while something is playing, and only from the Home tab — nobody wants the
    // screen taken over mid-way through changing a setting. A delay of 0 means on-demand only.
    LaunchedEffect(lastInteraction, isPlaying, selectedTab, ambientEnabled, ambientDelaySec) {
        if (!ambientEnabled || ambientDelaySec <= 0) return@LaunchedEffect
        if (!isPlaying || selectedTab != TvTab.HOME || ambientActive) return@LaunchedEffect
        delay(ambientDelaySec * 1000L)
        ambientActive = true
    }

    BackHandler(enabled = ambientActive || selectedTab != TvTab.HOME) {
        if (ambientActive) {
            ambientActive = false
            lastInteraction = System.currentTimeMillis()
        } else {
            selectedTab = TvTab.HOME
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
                    val isTransport = when (keyEvent.nativeKeyEvent.keyCode) {
                        android.view.KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                        android.view.KeyEvent.KEYCODE_MEDIA_PLAY,
                        android.view.KeyEvent.KEYCODE_MEDIA_PAUSE,
                        android.view.KeyEvent.KEYCODE_MEDIA_NEXT,
                        android.view.KeyEvent.KEYCODE_MEDIA_PREVIOUS -> true
                        else -> false
                    }
                    if (!isTransport) {
                        ambientActive = false
                        return@onPreviewKeyEvent true
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
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 48.dp, vertical = 27.dp)
        ) {
            TvSidebar(
                selectedTab = selectedTab,
                onTabSelected = { selectedTab = it }
            )

            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .padding(start = 24.dp)
            ) {
                when (selectedTab) {
                    TvTab.HOME -> TvHomeContent(
                        viewModel = viewModel,
                        onAlbumClick = onNavigateToAlbum,
                        ambientColor = animatedBg,
                        onEnterAmbient = { ambientActive = true },
                        claimInitialFocus = !homeFocusClaimed,
                        onInitialFocusClaimed = { homeFocusClaimed = true }
                    )
                    TvTab.SETTINGS -> TvSettingsContent(
                        viewModel = viewModel,
                        onDisconnected = onDisconnected
                    )
                }
            }
        }

        // Drawn OVER the screen rather than instead of it. The old screensaver swapped the
        // content tree out, which is what cost every bit of D-pad state and made the remote
        // feel dead on the way back; this leaves focus exactly where the user left it.
        val track = currentTrack
        if (ambientActive && track != null) {
            TvAmbientOverlay(viewModel = viewModel, track = track, isPlaying = isPlaying)
        }
    }
}

/**
 * The ambient / visualizer screen. Beat reactivity comes from the output-mix FFT when
 * RECORD_AUDIO has been granted; without it the particles drift and everything else still
 * works, so the permission is asked for once and never insisted upon.
 */
@Composable
private fun TvAmbientOverlay(
    viewModel: TvViewModel,
    track: Track,
    isPlaying: Boolean,
) {
    val beatReactive by viewModel.ambientBeatReactive.collectAsState()
    val bassLevel by viewModel.bassLevel.collectAsState()
    val fftMagnitudes by viewModel.fftMagnitudes.collectAsState()
    val context = LocalContext.current

    val permissionLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        contract = androidx.activity.result.contract.ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) viewModel.startVisualizer() }

    LaunchedEffect(beatReactive) {
        if (!beatReactive) return@LaunchedEffect
        val granted = androidx.core.content.ContextCompat.checkSelfPermission(
            context, android.Manifest.permission.RECORD_AUDIO
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        if (granted) viewModel.startVisualizer()
        else permissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
    }
    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose { viewModel.stopVisualizer() }
    }

    var positionMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(0L) }
    LaunchedEffect(track, isPlaying) {
        while (true) {
            positionMs = viewModel.getCurrentPosition()
            durationMs = viewModel.getDuration()
            delay(1000L)
        }
    }

    val palette = remember(track.coverArt) {
        listOf(ZonikColors.gold, Color(0xFF7C4DFF), Color(0xFF534AB7))
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Brush.radialGradient(listOf(Color(0xFF16121F), Color(0xFF07060B))))
    ) {
        ParticleSystem(
            bassLevel = if (beatReactive) bassLevel else 0f,
            fftMagnitudes = fftMagnitudes,
            colors = palette,
            modifier = Modifier.fillMaxSize(),
            centerX = 0.5f,
            centerY = 0.38f
        )

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 48.dp, vertical = 27.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            CoverArt(
                coverArtId = track.coverArt,
                contentDescription = track.title,
                modifier = Modifier
                    .size(320.dp)
                    .clip(ZonikShapes.coverArtLargeShape),
                size = 600
            )
            Spacer(modifier = Modifier.height(32.dp))
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

// ──────────────────────────────────────────────────────────────────────────────
// Sidebar Navigation
// ──────────────────────────────────────────────────────────────────────────────

@Composable
private fun TvSidebar(
    selectedTab: TvTab,
    onTabSelected: (TvTab) -> Unit
) {
    val sidebarIcons = mapOf(
        TvTab.HOME to Icons.Default.Home,
        TvTab.SETTINGS to Icons.Default.Settings
    )

    Column(
        modifier = Modifier
            .fillMaxHeight()
            .width(80.dp)
            .background(Color(0xFF1A1824))
            .padding(vertical = 27.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // Logo at top
        Icon(
            painter = androidx.compose.ui.res.painterResource(id = com.zonik.app.R.drawable.ic_logo_z),
            contentDescription = "Zonik",
            tint = ZonikColors.gold,
            modifier = Modifier.size(32.dp)
        )

        Spacer(modifier = Modifier.height(32.dp))

        // Nav items
        TvTab.entries.forEach { tab ->
            val isSelected = tab == selectedTab
            val icon = sidebarIcons[tab] ?: Icons.Default.Home
            Column(
                modifier = Modifier
                    .padding(vertical = 4.dp)
                    .size(64.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(
                        if (isSelected) ZonikColors.gold.copy(alpha = 0.15f)
                        else Color.Transparent
                    )
                    .tvFocusHighlight(RoundedCornerShape(12.dp))
                    .clickable { onTabSelected(tab) },
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = tab.label,
                    tint = if (isSelected) ZonikColors.gold else Color.White.copy(alpha = 0.5f),
                    modifier = Modifier.size(24.dp)
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = tab.label,
                    style = MaterialTheme.typography.labelSmall,
                    color = if (isSelected) ZonikColors.gold else Color.White.copy(alpha = 0.5f)
                )
            }
        }
    }
}

// ──────────────────────────────────────────────────────────────────────────────
// Home Tab
// ──────────────────────────────────────────────────────────────────────────────

@Composable
private fun TvHomeContent(
    viewModel: TvViewModel,
    onAlbumClick: (String) -> Unit,
    ambientColor: Color = TvCardBackground,
    onEnterAmbient: () -> Unit = {},
    claimInitialFocus: Boolean = true,
    onInitialFocusClaimed: () -> Unit = {}
) {
    val currentTrack by viewModel.currentTrack.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()
    val scrollState = rememberScrollState()

    // Nothing was focused at launch, so the first press of the remote was always
    // spent blindly acquiring focus instead of doing something. Only on the first composition
    // of the session, though — see homeFocusClaimed.
    val firstTile = remember { FocusRequester() }
    LaunchedEffect(claimInitialFocus) {
        if (!claimInitialFocus) return@LaunchedEffect
        try {
            firstTile.requestFocus()
        } catch (_: IllegalStateException) {
            // Node not attached yet; the remote's first press will acquire focus normally.
        }
        onInitialFocusClaimed()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(vertical = 16.dp)
    ) {
        // Shuffle buttons side by side
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            // Shuffle Mix
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp)
                    .clip(ZonikShapes.buttonShape)
                    .background(
                        Brush.horizontalGradient(
                            listOf(ZonikColors.gradientStart, ZonikColors.gradientEnd)
                        ),
                        ZonikShapes.buttonShape
                    )
                    .tvFocusHighlight(ZonikShapes.buttonShape)
                    .focusRequester(firstTile)
                    .clickable { viewModel.shuffleMix() },
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Icon(Icons.Default.Shuffle, null, tint = Color.White, modifier = Modifier.size(24.dp))
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("Shuffle Mix", style = MaterialTheme.typography.titleLarge, color = Color.White, fontWeight = FontWeight.Bold)
                }
            }

            // Shuffle Favorites
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp)
                    .clip(ZonikShapes.buttonShape)
                    .background(TvCardBackground, ZonikShapes.buttonShape)
                    .border(1.dp, ZonikColors.gold.copy(alpha = 0.3f), ZonikShapes.buttonShape)
                    .tvFocusHighlight(ZonikShapes.buttonShape)
                    .clickable { viewModel.shuffleFavorites() },
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Icon(Icons.Default.Favorite, null, tint = ZonikColors.gold, modifier = Modifier.size(24.dp))
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("Shuffle Favorites", style = MaterialTheme.typography.titleLarge, color = ZonikColors.gold, fontWeight = FontWeight.Bold)
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // Recently Added + Release Date side by side
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp)
                    .clip(ZonikShapes.buttonShape)
                    .background(TvCardBackground, ZonikShapes.buttonShape)
                    .border(1.dp, ZonikColors.gold.copy(alpha = 0.3f), ZonikShapes.buttonShape)
                    .tvFocusHighlight(ZonikShapes.buttonShape)
                    .clickable { viewModel.shuffleRecentlyAdded() },
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Icon(Icons.Default.NewReleases, null, tint = ZonikColors.gold, modifier = Modifier.size(24.dp))
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("Recently Added", style = MaterialTheme.typography.titleLarge, color = ZonikColors.gold, fontWeight = FontWeight.Bold)
                }
            }

            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(56.dp)
                    .clip(ZonikShapes.buttonShape)
                    .background(TvCardBackground, ZonikShapes.buttonShape)
                    .border(1.dp, ZonikColors.gold.copy(alpha = 0.3f), ZonikShapes.buttonShape)
                    .tvFocusHighlight(ZonikShapes.buttonShape)
                    .clickable { viewModel.shuffleNewestByYear() },
                contentAlignment = Alignment.Center
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Icon(Icons.Default.CalendarMonth, null, tint = ZonikColors.gold, modifier = Modifier.size(24.dp))
                    Spacer(modifier = Modifier.width(12.dp))
                    Text("By Release Date", style = MaterialTheme.typography.titleLarge, color = ZonikColors.gold, fontWeight = FontWeight.Bold)
                }
            }
        }

        // Now Playing section
        if (currentTrack != null) {
            Spacer(modifier = Modifier.height(32.dp))
            Text(
                text = "Now Playing",
                style = MaterialTheme.typography.titleLarge,
                color = Color.White,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(16.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(
                        Brush.horizontalGradient(
                            listOf(
                                ambientColor.copy(alpha = 0.8f),
                                TvCardBackground
                            )
                        ),
                        ZonikShapes.cardShape
                    )
                    .padding(20.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                CoverArt(
                    coverArtId = currentTrack!!.coverArt,
                    contentDescription = currentTrack!!.title,
                    modifier = Modifier
                        .size(200.dp)
                        .clip(ZonikShapes.coverArtLargeShape),
                    size = 600
                )
                Spacer(modifier = Modifier.width(24.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = currentTrack!!.title,
                        style = MaterialTheme.typography.headlineMedium,
                        color = Color.White,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = currentTrack!!.artist,
                        style = MaterialTheme.typography.bodyLarge,
                        color = Color.White.copy(alpha = 0.7f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = currentTrack!!.album,
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = 0.5f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )

                    // Playback controls
                    Spacer(modifier = Modifier.height(16.dp))
                    val isStarred by viewModel.isStarred.collectAsState()
                    LaunchedEffect(currentTrack) { viewModel.refreshStarred() }
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        // Enter the visualizer on demand, rather than only after the idle delay
                        IconButton(
                            onClick = onEnterAmbient,
                            modifier = Modifier
                                .size(48.dp)
                                .tvFocusHighlight(CircleShape)
                        ) {
                            Icon(
                                Icons.Default.GraphicEq,
                                "Show visualizer",
                                tint = Color.White.copy(alpha = 0.5f),
                                modifier = Modifier.size(24.dp)
                            )
                        }

                        // Star/unstar
                        IconButton(
                            onClick = { viewModel.toggleStar() },
                            modifier = Modifier
                                .size(48.dp)
                                .tvFocusHighlight(CircleShape)
                        ) {
                            Icon(
                                if (isStarred) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                                if (isStarred) "Unstar" else "Star",
                                tint = if (isStarred) ZonikColors.gold else Color.White.copy(alpha = 0.5f),
                                modifier = Modifier.size(24.dp)
                            )
                        }
                        Spacer(modifier = Modifier.width(8.dp))
                        IconButton(
                            onClick = { viewModel.skipPrevious() },
                            modifier = Modifier
                                .size(48.dp)
                                .tvFocusHighlight(CircleShape)
                        ) {
                            Icon(Icons.Default.SkipPrevious, "Previous", tint = Color.White, modifier = Modifier.size(28.dp))
                        }
                        IconButton(
                            onClick = { viewModel.togglePlayPause() },
                            modifier = Modifier
                                .size(56.dp)
                                .background(
                                    Brush.horizontalGradient(listOf(ZonikColors.gradientStart, ZonikColors.gradientEnd)),
                                    CircleShape
                                )
                                .tvFocusHighlight(CircleShape)
                        ) {
                            Icon(
                                if (isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                                if (isPlaying) "Pause" else "Play",
                                tint = Color.White,
                                modifier = Modifier.size(32.dp)
                            )
                        }
                        IconButton(
                            onClick = { viewModel.skipNext() },
                            modifier = Modifier
                                .size(48.dp)
                                .tvFocusHighlight(CircleShape)
                        ) {
                            Icon(Icons.Default.SkipNext, "Next", tint = Color.White, modifier = Modifier.size(28.dp))
                        }
                    }

                    // Progress bar
                    Spacer(modifier = Modifier.height(12.dp))
                    var positionMs by remember { mutableLongStateOf(0L) }
                    var durationMs by remember { mutableLongStateOf(0L) }
                    LaunchedEffect(isPlaying, currentTrack) {
                        positionMs = viewModel.getCurrentPosition()
                        durationMs = viewModel.getDuration()
                        // A just-transitioned item reports no duration until its source is
                        // prepared. While paused nothing else re-reads, so a single sample
                        // would leave the bar empty and the label at a garbage value forever.
                        var settle = 0
                        while (durationMs <= 0 && settle < 20) {
                            delay(250L)
                            settle++
                            positionMs = viewModel.getCurrentPosition()
                            durationMs = viewModel.getDuration()
                        }
                        while (isPlaying) {
                            delay(500L)
                            positionMs = viewModel.getCurrentPosition()
                            durationMs = viewModel.getDuration()
                        }
                    }
                    val progress = if (durationMs > 0) (positionMs.toFloat() / durationMs) else 0f
                    LinearProgressIndicator(
                        progress = { progress },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(4.dp)
                            .clip(RoundedCornerShape(2.dp)),
                        color = ZonikColors.gold,
                        trackColor = Color.White.copy(alpha = 0.1f)
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(
                            text = formatDurationMs(positionMs),
                            style = MaterialTheme.typography.labelSmall,
                            color = Color.White.copy(alpha = 0.5f)
                        )
                        Text(
                            // An unprepared item reports C.TIME_UNSET, which formats as a
                            // seven-digit minute count.
                            text = if (durationMs > 0) formatDurationMs(durationMs) else "--:--",
                            style = MaterialTheme.typography.labelSmall,
                            color = Color.White.copy(alpha = 0.5f)
                        )
                    }
                }
            }
        }

        // Bottom spacing for playback bar clearance
        Spacer(modifier = Modifier.height(80.dp))
    }
}

@Composable
private fun TvSettingsContent(
    viewModel: TvViewModel,
    onDisconnected: () -> Unit
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val syncState by viewModel.syncState.collectAsState()
    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
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

        // Visualizer — on/off
        val ambientOn by viewModel.ambientEnabled.collectAsState()
        TvSettingsButton(
            icon = Icons.Default.GraphicEq,
            title = "Visualizer",
            subtitle = if (ambientOn) "On — press OK to turn off" else "Off — press OK to turn on",
            onClick = { viewModel.setAmbientEnabled(!ambientOn) }
        )

        // Visualizer — idle delay. Cycles rather than opening a picker: one row, one button,
        // no nested focus to get lost in.
        val ambientDelay by viewModel.ambientDelaySec.collectAsState()
        TvSettingsButton(
            icon = Icons.Default.Sync,
            title = "Start visualizer after",
            subtitle = when (ambientDelay) {
                0 -> "Only when I ask for it"
                else -> "$ambientDelay seconds idle — press OK to change"
            },
            onClick = {
                val steps = listOf(0, 10, 30, 60, 90, 300)
                val next = steps[(steps.indexOf(ambientDelay).takeIf { it >= 0 }?.plus(1) ?: 1) % steps.size]
                viewModel.setAmbientDelaySec(next)
            }
        )

        // Visualizer — beat reactivity
        val beatOn by viewModel.ambientBeatReactive.collectAsState()
        TvSettingsButton(
            icon = Icons.Default.MusicNote,
            title = "React to the music",
            subtitle = if (beatOn) "On — needs microphone permission to read the audio"
                       else "Off — the visuals drift on their own",
            onClick = { viewModel.setAmbientBeatReactive(!beatOn) }
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
    tint: Color = Color.White
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(TvCardBackground, ZonikShapes.cardShape)
            .tvFocusHighlight(ZonikShapes.cardShape)
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

