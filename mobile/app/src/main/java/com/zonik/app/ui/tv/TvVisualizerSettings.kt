package com.zonik.app.ui.tv

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.zonik.app.ui.theme.ZonikColors
import com.zonik.app.ui.util.tvFocusLift

private val RowShape = RoundedCornerShape(8.dp)
private val CardFill = Color(0xFF1E1C2A)
private val CardFillOff = Color(0xFF1B1A21)
/**
 * Ten to a row, one line each at 10sp, so all of the effects (93 of them) fit below the settings
 * in ten rows without scrolling. Should the list outgrow that, the grid scrolls to keep the
 * focused card in view.
 */
private const val CARDS_PER_ROW = 10

/**
 * The visualizer's own settings page: settings on the left, a live preview of the focused
 * effect on the right, and every effect as a card below that OK adds to or removes from the
 * rotation.
 *
 * Laid out for a 960x540dp TV canvas without scrolling, so the preview never slides out of view
 * while the remote is moving through the cards. Every row cycles on OK rather than opening a
 * picker — one row, one button, no nested focus to get lost in.
 */
@Composable
fun TvVisualizerSettings(viewModel: TvViewModel, onBack: () -> Unit) {
    BackHandler(onBack = onBack)

    val ambientOn by viewModel.ambientEnabled.collectAsState()
    val delaySec by viewModel.ambientDelaySec.collectAsState()
    val beatOn by viewModel.ambientBeatReactive.collectAsState()
    val rotateSec by viewModel.ambientRotateSec.collectAsState()
    val infoMode by viewModel.ambientInfo.collectAsState()
    val transition by viewModel.ambientTransition.collectAsState()
    val transitionMs by viewModel.ambientTransitionMs.collectAsState()
    val colors by viewModel.ambientColors.collectAsState()
    val trails by viewModel.ambientTrails.collectAsState()
    val enabled by viewModel.ambientEffects.collectAsState()

    val track by viewModel.currentTrack.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()
    val bpm by viewModel.trackBpm.collectAsState()
    val art = rememberAmbientArt(track?.coverArt)
    val beatClock = remember(track?.id, bpm) { BeatClock(bpm) }
    if (isPlaying) AudioCaptureEffect(viewModel)

    TvVisualizerSettingsContent(
        state = VisualizerSettingsState(
            ambientOn = ambientOn, delaySec = delaySec, beatOn = beatOn, rotateSec = rotateSec,
            infoMode = infoMode, transition = transition, transitionMs = transitionMs, colors = colors,
            trails = trails, enabled = enabled,
            isPlaying = isPlaying,
        ),
        actions = VisualizerSettingsActions(
            setAmbientEnabled = viewModel::setAmbientEnabled,
            setDelaySec = viewModel::setAmbientDelaySec,
            setBeatReactive = viewModel::setAmbientBeatReactive,
            setRotateSec = viewModel::setAmbientRotateSec,
            setInfo = viewModel::setAmbientInfo,
            setTransition = viewModel::setAmbientTransition,
            setTransitionMs = viewModel::setAmbientTransitionMs,
            setColors = viewModel::setAmbientColors,
            setTrails = viewModel::setAmbientTrails,
            setEffects = viewModel::setAmbientEffects,
            toggleEffect = viewModel::toggleAmbientEffect,
        ),
    ) { effect ->
        DemoVisualizer(
            effect = effect,
            pulse = viewModel.pulse,
            beatClock = beatClock,
            cover = art.cover,
            palette = art.palette,
            transition = transition,
            transitionMs = transitionMs,
            colors = colors,
            title = track?.let { "${it.title}  ·  ${it.artist}" } ?: "Zonik",
            trails = trails,
            modifier = Modifier.fillMaxSize()
        )
    }
}

/** What the visualizer page shows, so its body can be drawn without a view model (screenshots). */
internal data class VisualizerSettingsState(
    val ambientOn: Boolean,
    val delaySec: Int,
    val beatOn: Boolean,
    val rotateSec: Int,
    val infoMode: String,
    val transition: Int,
    val transitionMs: Int,
    val colors: String,
    val trails: Boolean,
    val enabled: List<DemoEffect>,
    val isPlaying: Boolean,
)

internal class VisualizerSettingsActions(
    val setAmbientEnabled: (Boolean) -> Unit,
    val setDelaySec: (Int) -> Unit,
    val setBeatReactive: (Boolean) -> Unit,
    val setRotateSec: (Int) -> Unit,
    val setInfo: (String) -> Unit,
    val setTransition: (Int) -> Unit,
    val setTransitionMs: (Int) -> Unit,
    val setColors: (String) -> Unit,
    val setTrails: (Boolean) -> Unit,
    val setEffects: (Set<DemoEffect>) -> Unit,
    val toggleEffect: (DemoEffect) -> Unit,
)

/** The page itself; [preview] draws the live effect into the preview box. */
@OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class) // FocusRequester.Cancel
@Composable
internal fun TvVisualizerSettingsContent(
    state: VisualizerSettingsState,
    actions: VisualizerSettingsActions,
    preview: @Composable (DemoEffect) -> Unit,
) {
    val ambientOn = state.ambientOn
    val delaySec = state.delaySec
    val beatOn = state.beatOn
    val rotateSec = state.rotateSec
    val infoMode = state.infoMode
    val transition = state.transition
    val transitionMs = state.transitionMs
    val colors = state.colors
    val trails = state.trails
    val enabled = state.enabled
    val isPlaying = state.isPlaying
    var previewEffect by remember { mutableStateOf(enabled.firstOrNull() ?: DemoEffect.entries.first()) }
    val firstRow = remember { FocusRequester() }
    val firstCard = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { firstRow.requestFocus() } }

    Column(
        modifier = Modifier.fillMaxSize().padding(vertical = 2.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "Visualizer",
                style = MaterialTheme.typography.headlineSmall,
                color = Color.White,
                modifier = Modifier.weight(1f)
            )
            Text(
                "BACK to return",
                style = MaterialTheme.typography.labelMedium,
                color = Color.White.copy(alpha = 0.4f)
            )
        }

        Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(2.dp)
            ) {
                SettingRow(
                    "Visualizer", if (ambientOn) "On" else "Off",
                    modifier = Modifier.focusRequester(firstRow)
                ) { actions.setAmbientEnabled(!ambientOn) }
                SettingRow("Start after", delayLabel(delaySec)) {
                    actions.setDelaySec(cycle(DELAY_STEPS, delaySec))
                }
                SettingRow("React to music", if (beatOn) "On" else "Off") {
                    actions.setBeatReactive(!beatOn)
                }
                SettingRow("Change effect", rotateLabel(rotateSec)) {
                    actions.setRotateSec(cycle(ROTATE_STEPS, rotateSec))
                }
                SettingRow("Track info", INFO_LABELS[infoMode] ?: "Centre, then fade") {
                    actions.setInfo(cycle(INFO_LABELS.keys.toList(), infoMode))
                }
                SettingRow(
                    "Transitions",
                    DEMO_TRANSITIONS.getOrNull(transition) ?: "Mixed",
                ) {
                    actions.setTransition(cycle((-1 until DEMO_TRANSITIONS.size).toList(), transition))
                }
                SettingRow("Transition speed", TRANSITION_SPEEDS[transitionMs] ?: "${transitionMs} ms") {
                    actions.setTransitionMs(cycle(TRANSITION_SPEEDS.keys.toList(), transitionMs))
                }
                SettingRow("Colours", COLOR_LABELS[colors] ?: "Album art") {
                    actions.setColors(cycle(COLOR_LABELS.keys.toList(), colors))
                }
                SettingRow(
                    "Trails",
                    if (trails) "On" else "Off",
                    // Straight down to the first card, rather than whichever card happens to
                    // sit under this row's centre.
                    modifier = Modifier.focusProperties { down = firstCard }
                ) {
                    actions.setTrails(!trails)
                }
            }

            Column(modifier = Modifier.width(260.dp)) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(16f / 9f)
                        .border(1.dp, Color.White.copy(alpha = 0.15f))
                ) {
                    preview(previewEffect)
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    buildString {
                        append(previewEffect.label)
                        append(
                            when {
                                previewEffect in COVER_EFFECTS -> " · built from the cover"
                                colors == "RANDOM" -> " · random colours"
                                colors == "CYCLE" -> " · cycling colours"
                                colors == "MIXED" -> " · mixed colours"
                                else -> " · cover colours"
                            }
                        )
                        if (!isPlaying) append(" · play something to see it react")
                    },
                    style = MaterialTheme.typography.labelMedium,
                    color = Color.White.copy(alpha = 0.6f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "EFFECTS IN ROTATION",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = Color.White.copy(alpha = 0.8f)
            )
            Text(
                "  OK adds or removes · ${enabled.size} of ${DemoEffect.entries.size} on",
                style = MaterialTheme.typography.labelMedium,
                color = Color.White.copy(alpha = 0.45f),
                modifier = Modifier.weight(1f)
            )
            ChipButton("All") { actions.setEffects(DemoEffect.entries.toSet()) }
            Spacer(Modifier.width(8.dp))
            ChipButton("No cover art") {
                actions.setEffects(DemoEffect.entries.toSet() - COVER_EFFECTS)
            }
        }

        // Scrolls only if the effects outgrow the space; focusing a card brings it into view.
        Column(
            modifier = Modifier.weight(1f).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            DemoEffect.entries.chunked(CARDS_PER_ROW).forEach { rowEffects ->
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    rowEffects.forEachIndexed { index, effect ->
                        EffectCard(
                            effect = effect,
                            on = effect in enabled,
                            onFocused = { previewEffect = effect },
                            onClick = { actions.toggleEffect(effect) },
                            modifier = Modifier
                                .weight(1f)
                                .then(if (effect.ordinal == 0) Modifier.focusRequester(firstCard) else Modifier)
                                // RIGHT stops at the end of a row. Left to itself, focus search
                                // from the short last row jumps diagonally up into the row above.
                                .then(
                                    if (index == rowEffects.lastIndex) Modifier.focusProperties { right = FocusRequester.Cancel }
                                    else Modifier
                                )
                        )
                    }
                    // Keep a short last row's cards the same width as the full rows above.
                    repeat(CARDS_PER_ROW - rowEffects.size) { Spacer(Modifier.weight(1f)) }
                }
            }
        }
    }
}

@Composable
private fun SettingRow(
    title: String,
    value: String,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(20.dp)
            .tvFocusLift(RowShape, scale = 1.02f)
            .background(CardFill, RowShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(title, style = MaterialTheme.typography.bodySmall, color = Color.White, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.labelMedium, color = ZonikColors.gold)
    }
}

/**
 * One effect in the gallery. An effect in the rotation wears the app's purple gradient (the same
 * one as Shuffle Mix); one left out is flat grey with faded type — readable from across the
 * room without a checkmark. The gold border is kept for focus alone, so the remote's position
 * is never mistaken for "on".
 */
@Composable
private fun EffectCard(
    effect: DemoEffect,
    on: Boolean,
    onFocused: () -> Unit,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val fill = if (on) {
        Brush.horizontalGradient(listOf(ZonikColors.gradientStart, ZonikColors.gradientEnd))
    } else {
        Brush.horizontalGradient(listOf(CardFillOff, CardFillOff))
    }
    Box(
        modifier = modifier
            .height(18.dp)
            .onFocusChanged { if (it.isFocused) onFocused() }
            .tvFocusLift(RowShape)
            .background(fill, RowShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 3.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            effect.label,
            style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp),
            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
            color = if (on) Color.White else Color.White.copy(alpha = 0.28f),
            textAlign = TextAlign.Center,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        // Built from the cover image (rather than only its colours): a small gold mark in the
        // corner, since a second "cover art" line no longer fits the one-line cards.
        if (effect in COVER_EFFECTS) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 3.dp)
                    .width(4.dp)
                    .height(4.dp)
                    .background(ZonikColors.gold.copy(alpha = if (on) 0.9f else 0.3f), RoundedCornerShape(50))
            )
        }
    }
}

@Composable
private fun ChipButton(label: String, onClick: () -> Unit) {
    Text(
        label,
        style = MaterialTheme.typography.labelMedium,
        color = Color.White,
        modifier = Modifier
            .tvFocusLift(RoundedCornerShape(50))
            .background(CardFill, RoundedCornerShape(50))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp)
    )
}

private val DELAY_STEPS = listOf(0, 10, 30, 60, 90, 300)
private val ROTATE_STEPS = listOf(0, 30, 45, 60, 120, 300)
private val COLOR_LABELS = linkedMapOf(
    "ALBUM" to "Album art",
    "RANDOM" to "Random",
    "CYCLE" to "Cycle",
    "MIXED" to "Mixed",
)

/** Transition length in ms, and its label. */
private val TRANSITION_SPEEDS = linkedMapOf(
    600 to "Fast",
    1600 to "Normal",
    3000 to "Slow",
    5000 to "Very slow",
)
private val INFO_LABELS = linkedMapOf(
    "FADE" to "Centre, then fade",
    "ALWAYS" to "Centre, always",
    "CORNER_FADE" to "Corner, then fade",
    "CORNER_ALWAYS" to "Corner, always",
    "NEVER" to "Never",
)

private fun <T> cycle(options: List<T>, current: T): T =
    options[(options.indexOf(current) + 1).mod(options.size)]

private fun delayLabel(sec: Int) = when {
    sec == 0 -> "Only when asked"
    sec < 60 -> "$sec s idle"
    sec % 60 == 0 -> "${sec / 60} min idle"
    else -> "$sec s idle"
}

private fun rotateLabel(sec: Int) = when {
    sec == 0 -> "Each track"
    sec < 60 -> "Every $sec s"
    sec == 60 -> "Every minute"
    else -> "Every ${sec / 60} min"
}
