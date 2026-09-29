package com.zonik.app.ui.tv

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.NewReleases
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Shuffle
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.zonik.app.ui.components.CoverArt
import com.zonik.app.ui.theme.ZonikColors
import com.zonik.app.ui.util.formatDurationMs
import com.zonik.app.ui.util.tvFocusLift
import com.zonik.core.model.Track
import kotlinx.coroutines.delay

/** What sits over the Stage: nothing, the UP actions strip, or the DOWN browse rails. */
enum class StagePanel { NONE, STRIP, BROWSE }

private val CardFill = Color(0xFF1E1C2A)
private val PanelFill = Color(0xF2141220)

/**
 * The TV's root: Now Playing is the whole screen, because it is what a TV music app shows most
 * of the time. Everything else is one press away and never unmounts it — UP opens the actions
 * strip, DOWN slides the browse rails up while the music keeps playing, BACK closes either.
 * With nothing playing, the browse rails open by themselves: there is nothing else to look at.
 */
@Composable
fun TvStage(
    viewModel: TvViewModel,
    panel: StagePanel,
    onPanelChange: (StagePanel) -> Unit,
    onEnterAmbient: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val track by viewModel.currentTrack.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()
    val queue by viewModel.queue.collectAsState()

    val playFocus = remember { FocusRequester() }
    val stripFocus = remember { FocusRequester() }
    val browseFocus = remember { FocusRequester() }

    val nothingPlaying = track == null
    LaunchedEffect(nothingPlaying) {
        if (nothingPlaying) onPanelChange(StagePanel.BROWSE)
    }

    // Focus follows the panel. The target may only just be composing (a panel sliding in, the
    // hero switching layout), so give it a few frames to attach before giving up.
    LaunchedEffect(panel, nothingPlaying) {
        val target = when {
            panel == StagePanel.STRIP -> stripFocus
            panel == StagePanel.BROWSE || nothingPlaying -> browseFocus
            else -> playFocus
        }
        repeat(5) {
            withFrameNanos { }
            if (runCatching { target.requestFocus() }.isSuccess) return@LaunchedEffect
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val current = track
        if (current != null) {
            val index = queue.indexOfFirst { it.id == current.id }
            NowPlayingHero(
                viewModel = viewModel,
                track = current,
                isPlaying = isPlaying,
                upNext = if (index >= 0) queue.getOrNull(index + 1) else null,
                compact = panel == StagePanel.BROWSE,
                playFocus = playFocus,
                onEnterAmbient = onEnterAmbient,
                onUp = { onPanelChange(StagePanel.STRIP) },
                onDown = { onPanelChange(StagePanel.BROWSE) },
            )
        } else {
            Column(modifier = Modifier.padding(top = 8.dp)) {
                Text("Nothing playing", style = MaterialTheme.typography.headlineMedium, color = Color.White)
                Text(
                    "Pick a mix, an album or a playlist below",
                    style = MaterialTheme.typography.bodyLarge,
                    color = Color.White.copy(alpha = 0.6f)
                )
            }
        }

        AnimatedVisibility(
            visible = panel == StagePanel.STRIP,
            enter = slideInVertically { -it } + fadeIn(),
            exit = slideOutVertically { -it } + fadeOut(),
            modifier = Modifier.align(Alignment.TopCenter)
        ) {
            ActionStrip(
                viewModel = viewModel,
                hasTrack = !nothingPlaying,
                firstFocus = stripFocus,
                // With nothing playing, "closed" means back to the rails, not an empty Stage.
                onClose = { onPanelChange(if (nothingPlaying) StagePanel.BROWSE else StagePanel.NONE) },
                onEnterAmbient = onEnterAmbient,
                onOpenSettings = onOpenSettings,
            )
        }

        AnimatedVisibility(
            visible = panel == StagePanel.BROWSE,
            enter = slideInVertically { it } + fadeIn(),
            exit = slideOutVertically { it } + fadeOut(),
            modifier = Modifier.align(Alignment.BottomCenter)
        ) {
            BrowseRails(
                viewModel = viewModel,
                firstFocus = browseFocus,
                fullHeight = nothingPlaying,
                // With nothing playing there is no Stage to go back up to; UP opens the strip.
                onUpFromTop = {
                    onPanelChange(if (nothingPlaying) StagePanel.STRIP else StagePanel.NONE)
                },
            )
        }
    }
}

// ─── Now Playing ────────────────────────────────────────────────────────────────

@Composable
private fun NowPlayingHero(
    viewModel: TvViewModel,
    track: Track,
    isPlaying: Boolean,
    upNext: Track?,
    compact: Boolean,
    playFocus: FocusRequester,
    onEnterAmbient: () -> Unit,
    onUp: () -> Unit,
    onDown: () -> Unit,
) {
    val (positionMs, durationMs) = rememberPlaybackProgress(viewModel, track, isPlaying)
    val progress = if (durationMs > 0) positionMs.toFloat() / durationMs else 0f

    if (compact) {
        // Browse is open: the Stage shrinks to a header and keeps playing.
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            CoverArt(
                coverArtId = track.coverArt,
                contentDescription = track.title,
                modifier = Modifier.size(64.dp).clip(RoundedCornerShape(8.dp)),
                size = 200
            )
            Spacer(Modifier.width(16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(track.title, style = MaterialTheme.typography.titleLarge, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(track.artist, style = MaterialTheme.typography.bodyMedium, color = Color.White.copy(alpha = 0.65f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(6.dp))
                ProgressBar(progress, Modifier.width(320.dp))
            }
            Icon(Icons.Default.KeyboardArrowUp, null, tint = Color.White.copy(alpha = 0.4f))
            Text("Now playing", style = MaterialTheme.typography.labelMedium, color = Color.White.copy(alpha = 0.4f))
        }
        return
    }

    val isStarred by viewModel.isStarred.collectAsState()
    LaunchedEffect(track.id) { viewModel.refreshStarred() }

    Box(modifier = Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.align(Alignment.TopCenter).padding(top = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Icon(Icons.Default.KeyboardArrowUp, null, tint = Color.White.copy(alpha = 0.35f), modifier = Modifier.size(16.dp))
            Text("Mixes · Visualizer · Settings", style = MaterialTheme.typography.labelMedium, color = Color.White.copy(alpha = 0.35f))
        }

        Row(
            modifier = Modifier.align(Alignment.CenterStart).padding(start = 24.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(48.dp)
        ) {
            CoverArt(
                coverArtId = track.coverArt,
                contentDescription = track.title,
                modifier = Modifier.size(300.dp).clip(RoundedCornerShape(16.dp)),
                size = 600
            )
            Column(modifier = Modifier.width(460.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("NOW PLAYING", style = MaterialTheme.typography.labelMedium, color = ZonikColors.gold, fontWeight = FontWeight.Medium)
                Text(track.title, style = MaterialTheme.typography.headlineLarge, color = Color.White, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(
                    listOf(track.artist, track.album).filter { it.isNotBlank() }.joinToString(" — "),
                    style = MaterialTheme.typography.titleMedium,
                    color = Color.White.copy(alpha = 0.72f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.height(6.dp))
                ProgressBar(progress, Modifier.fillMaxWidth())
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(formatDurationMs(positionMs), style = MaterialTheme.typography.labelSmall, color = Color.White.copy(alpha = 0.5f))
                    // An unprepared item reports C.TIME_UNSET, which formats as a seven-digit
                    // minute count.
                    Text(if (durationMs > 0) formatDurationMs(durationMs) else "--:--", style = MaterialTheme.typography.labelSmall, color = Color.White.copy(alpha = 0.5f))
                }
                // UP and DOWN on the transport open the strip and the rails; LEFT and RIGHT
                // walk the buttons as usual.
                Row(
                    modifier = Modifier.padding(top = 8.dp).onPreviewKeyEvent { e ->
                        if (e.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
                        when (e.key) {
                            Key.DirectionUp -> { onUp(); true }
                            Key.DirectionDown -> { onDown(); true }
                            else -> false
                        }
                    },
                    horizontalArrangement = Arrangement.spacedBy(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    RoundButton(Icons.Default.GraphicEq, "Show visualizer", 48, onClick = onEnterAmbient)
                    RoundButton(Icons.Default.SkipPrevious, "Previous", 52, onClick = { viewModel.skipPrevious() })
                    RoundButton(
                        if (isPlaying) Icons.Default.Pause else Icons.Default.PlayArrow,
                        if (isPlaying) "Pause" else "Play",
                        68,
                        primary = true,
                        modifier = Modifier.focusRequester(playFocus),
                        onClick = { viewModel.togglePlayPause() }
                    )
                    RoundButton(Icons.Default.SkipNext, "Next", 52, onClick = { viewModel.skipNext() })
                    RoundButton(
                        if (isStarred) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                        if (isStarred) "Unstar" else "Star",
                        48,
                        tint = if (isStarred) ZonikColors.gold else Color.White.copy(alpha = 0.7f),
                        onClick = { viewModel.toggleStar() }
                    )
                }
                if (upNext != null) {
                    Text(
                        "Up next · ${upNext.title} — ${upNext.artist}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Color.White.copy(alpha = 0.6f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(top = 6.dp)
                    )
                }
            }
        }

        Row(
            modifier = Modifier.align(Alignment.BottomCenter),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            Icon(Icons.Default.KeyboardArrowDown, null, tint = Color.White.copy(alpha = 0.35f), modifier = Modifier.size(16.dp))
            Text("Browse albums and playlists", style = MaterialTheme.typography.labelMedium, color = Color.White.copy(alpha = 0.35f))
        }
    }
}

/**
 * Position and duration, re-read twice a second while playing. A just-changed item reports no
 * duration until its source is prepared, so it keeps sampling briefly even while paused rather
 * than freezing on an empty bar and a garbage label.
 */
@Composable
private fun rememberPlaybackProgress(viewModel: TvViewModel, track: Track, isPlaying: Boolean): Pair<Long, Long> {
    var positionMs by remember { mutableLongStateOf(0L) }
    var durationMs by remember { mutableLongStateOf(0L) }
    LaunchedEffect(isPlaying, track.id) {
        positionMs = viewModel.getCurrentPosition()
        durationMs = viewModel.getDuration()
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
    return positionMs to durationMs
}

@Composable
private fun ProgressBar(progress: Float, modifier: Modifier) {
    LinearProgressIndicator(
        progress = { progress },
        modifier = modifier.height(5.dp).clip(RoundedCornerShape(3.dp)),
        color = ZonikColors.gold,
        trackColor = Color.White.copy(alpha = 0.14f)
    )
}

@Composable
private fun RoundButton(
    icon: ImageVector,
    description: String,
    sizeDp: Int,
    modifier: Modifier = Modifier,
    primary: Boolean = false,
    tint: Color = Color.White,
    onClick: () -> Unit,
) {
    Box(
        modifier = modifier
            .size(sizeDp.dp)
            .tvFocusLift(CircleShape, scale = 1.1f)
            .clip(CircleShape)
            .background(
                if (primary) Brush.horizontalGradient(listOf(ZonikColors.gradientStart, ZonikColors.gradientEnd))
                else Brush.horizontalGradient(listOf(Color.White.copy(alpha = 0.08f), Color.White.copy(alpha = 0.08f)))
            )
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center
    ) {
        Icon(icon, description, tint = tint, modifier = Modifier.size((sizeDp * 0.46f).dp))
    }
}

// ─── UP: actions strip ──────────────────────────────────────────────────────────

@Composable
private fun ActionStrip(
    viewModel: TvViewModel,
    hasTrack: Boolean,
    firstFocus: FocusRequester,
    onClose: () -> Unit,
    onEnterAmbient: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(PanelFill)
            // Scrolls rather than clipping if a longer label ever pushes it past the screen;
            // focus brings the off-screen end into view by itself.
            .horizontalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 14.dp)
            .onPreviewKeyEvent { e ->
                if (e.type == KeyEventType.KeyDown && e.key == Key.DirectionDown) {
                    onClose()
                    true
                } else {
                    false
                }
            },
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        StripButton(Icons.Default.Shuffle, "Shuffle mix", primary = true, modifier = Modifier.focusRequester(firstFocus)) {
            viewModel.shuffleMix(); onClose()
        }
        StripButton(Icons.Default.Favorite, "Favorites") { viewModel.shuffleFavorites(); onClose() }
        StripButton(Icons.Default.NewReleases, "Recently added") { viewModel.shuffleRecentlyAdded(); onClose() }
        StripButton(Icons.Default.CalendarMonth, "By year") { viewModel.shuffleNewestByYear(); onClose() }
        if (hasTrack) StripButton(Icons.Default.GraphicEq, "Visualizer") { onClose(); onEnterAmbient() }
        StripButton(Icons.Default.Settings, "Settings", onClick = onOpenSettings)
    }
}

@Composable
private fun StripButton(
    icon: ImageVector,
    label: String,
    modifier: Modifier = Modifier,
    primary: Boolean = false,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(24.dp)
    Row(
        modifier = modifier
            .height(48.dp)
            .tvFocusLift(shape)
            .clip(shape)
            .background(
                if (primary) Brush.horizontalGradient(listOf(ZonikColors.gradientStart, ZonikColors.gradientEnd))
                else Brush.horizontalGradient(listOf(CardFill, CardFill))
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Icon(icon, null, tint = if (primary) Color.White else ZonikColors.gold, modifier = Modifier.size(18.dp))
        Text(label, style = MaterialTheme.typography.labelLarge, color = if (primary) Color.White else ZonikColors.gold)
    }
}

// ─── DOWN: browse rails ─────────────────────────────────────────────────────────

@Composable
private fun BrowseRails(
    viewModel: TvViewModel,
    firstFocus: FocusRequester,
    fullHeight: Boolean,
    onUpFromTop: () -> Unit,
) {
    LaunchedEffect(Unit) { viewModel.loadBrowse() }
    val recentlyPlayed by viewModel.recentlyPlayedAlbums.collectAsState()
    val recentlyAdded by viewModel.recentAlbums.collectAsState()
    val playlists by viewModel.playlists.collectAsState()

    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .fillMaxHeight(if (fullHeight) 0.84f else 0.82f)
            .clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp))
            .background(PanelFill),
        contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = 16.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        item {
            Rail("Mixes") {
                // UP from the first rail leaves browse; lower rails move up normally.
                LazyRow(
                    modifier = Modifier.onPreviewKeyEvent { e ->
                        if (e.type == KeyEventType.KeyDown && e.key == Key.DirectionUp) { onUpFromTop(); true } else false
                    },
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                    // Room for the focus lift and glow, which a LazyRow would otherwise clip into a box.
                    contentPadding = PaddingValues(horizontal = 20.dp, vertical = 20.dp)
                ) {
                    item { MixCard(Icons.Default.Shuffle, "Shuffle mix", primary = true, modifier = Modifier.focusRequester(firstFocus)) { viewModel.shuffleMix() } }
                    item { MixCard(Icons.Default.Favorite, "Favorites") { viewModel.shuffleFavorites() } }
                    item { MixCard(Icons.Default.NewReleases, "Recently added") { viewModel.shuffleRecentlyAdded() } }
                    item { MixCard(Icons.Default.CalendarMonth, "By release date") { viewModel.shuffleNewestByYear() } }
                }
            }
        }
        if (recentlyPlayed.isNotEmpty()) {
            item {
                Rail("Recently played") {
                    ArtRow(recentlyPlayed.map { Triple(it.coverArt, it.name, it.artist) }) { i -> viewModel.playAlbum(recentlyPlayed[i].id) }
                }
            }
        }
        if (recentlyAdded.isNotEmpty()) {
            item {
                Rail("Recently added albums") {
                    ArtRow(recentlyAdded.map { Triple(it.coverArt, it.name, it.artist) }) { i -> viewModel.playAlbum(recentlyAdded[i].id) }
                }
            }
        }
        if (playlists.isNotEmpty()) {
            item {
                Rail("Playlists") {
                    ArtRow(playlists.map { Triple(it.coverArt, it.name, "${it.songCount} songs") }) { i -> viewModel.playPlaylist(playlists[i].id) }
                }
            }
        }
    }
}

@Composable
private fun Rail(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, color = Color.White, fontWeight = FontWeight.Medium, modifier = Modifier.padding(start = 6.dp))
        content()
    }
}

@Composable
private fun MixCard(
    icon: ImageVector,
    label: String,
    modifier: Modifier = Modifier,
    primary: Boolean = false,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        modifier = modifier
            .width(200.dp)
            .height(76.dp)
            .tvFocusLift(shape)
            .clip(shape)
            .background(
                if (primary) Brush.horizontalGradient(listOf(ZonikColors.gradientStart, ZonikColors.gradientEnd))
                else Brush.horizontalGradient(listOf(CardFill, CardFill))
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Icon(icon, null, tint = if (primary) Color.White else ZonikColors.gold, modifier = Modifier.size(22.dp))
        Text(label, style = MaterialTheme.typography.titleSmall, color = if (primary) Color.White else ZonikColors.gold, fontWeight = FontWeight.Medium)
    }
}

/** A row of square artwork cards; OK on one calls [onPlay] with its index. */
@Composable
private fun ArtRow(items: List<Triple<String?, String, String>>, onPlay: (Int) -> Unit) {
    LazyRow(
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        // Room for the focus lift and glow, which a LazyRow would otherwise clip into a box.
                    contentPadding = PaddingValues(horizontal = 20.dp, vertical = 20.dp)
    ) {
        items(items.size) { i ->
            val (cover, title, subtitle) = items[i]
            val shape = RoundedCornerShape(12.dp)
            Column(modifier = Modifier.width(132.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Box(
                    modifier = Modifier
                        .size(132.dp)
                        .tvFocusLift(shape)
                        .clip(shape)
                        .clickable { onPlay(i) }
                ) {
                    CoverArt(coverArtId = cover, contentDescription = title, modifier = Modifier.fillMaxSize(), size = 300)
                }
                Text(title, style = MaterialTheme.typography.labelLarge, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(subtitle, style = MaterialTheme.typography.labelSmall, color = Color.White.copy(alpha = 0.55f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
