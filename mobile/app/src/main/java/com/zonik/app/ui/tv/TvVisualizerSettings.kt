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
import com.zonik.app.ui.theme.ZonikColors
import com.zonik.app.ui.util.tvFocusHighlight

private val RowShape = RoundedCornerShape(8.dp)
private val CardFill = Color(0xFF1E1C2A)
private val CardFillOff = Color(0xFF1B1A21)
/**
 * Three rows whatever the effect count, so the page fits one screen without scrolling and each
 * card is wide enough for its name on one line.
 */
private val CARDS_PER_ROW = (DemoEffect.entries.size + 2) / 3

/**
 * The visualizer's own settings page: settings on the left, a live preview of the focused
 * effect on the right, and every effect as a card below that OK adds to or removes from the
 * rotation.
 *
 * Laid out for a 960x540dp TV canvas without scrolling, so the preview never slides out of view
 * while the remote is moving through the cards. Every row cycles on OK rather than opening a
 * picker — one row, one button, no nested focus to get lost in.
 */
@OptIn(androidx.compose.ui.ExperimentalComposeUiApi::class) // FocusRequester.Cancel
@Composable
fun TvVisualizerSettings(viewModel: TvViewModel, onBack: () -> Unit) {
    BackHandler(onBack = onBack)

    val ambientOn by viewModel.ambientEnabled.collectAsState()
    val delaySec by viewModel.ambientDelaySec.collectAsState()
    val beatOn by viewModel.ambientBeatReactive.collectAsState()
    val rotateSec by viewModel.ambientRotateSec.collectAsState()
    val infoMode by viewModel.ambientInfo.collectAsState()
    val transition by viewModel.ambientTransition.collectAsState()
    val enabled by viewModel.ambientEffects.collectAsState()

    val track by viewModel.currentTrack.collectAsState()
    val isPlaying by viewModel.isPlaying.collectAsState()
    val bpm by viewModel.trackBpm.collectAsState()
    val art = rememberAmbientArt(track?.coverArt)
    val beatClock = remember(track?.id, bpm) { BeatClock(bpm) }
    if (isPlaying) AudioCaptureEffect(viewModel)

    var previewEffect by remember { mutableStateOf(enabled.first()) }
    val firstRow = remember { FocusRequester() }
    val firstCard = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { firstRow.requestFocus() } }

    Column(
        modifier = Modifier.fillMaxSize().padding(vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
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
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                SettingRow(
                    "Visualizer", if (ambientOn) "On" else "Off",
                    modifier = Modifier.focusRequester(firstRow)
                ) { viewModel.setAmbientEnabled(!ambientOn) }
                SettingRow("Start after", delayLabel(delaySec)) {
                    viewModel.setAmbientDelaySec(cycle(DELAY_STEPS, delaySec))
                }
                SettingRow("React to music", if (beatOn) "On" else "Off") {
                    viewModel.setAmbientBeatReactive(!beatOn)
                }
                SettingRow("Change effect", rotateLabel(rotateSec)) {
                    viewModel.setAmbientRotateSec(cycle(ROTATE_STEPS, rotateSec))
                }
                SettingRow("Track info", INFO_LABELS[infoMode] ?: "Show, then fade") {
                    viewModel.setAmbientInfo(cycle(INFO_LABELS.keys.toList(), infoMode))
                }
                SettingRow(
                    "Transitions",
                    DEMO_TRANSITIONS.getOrNull(transition) ?: "Mixed",
                    // Straight down to the first card, rather than whichever card happens to
                    // sit under this row's centre.
                    modifier = Modifier.focusProperties { down = firstCard }
                ) {
                    viewModel.setAmbientTransition(cycle((-1 until DEMO_TRANSITIONS.size).toList(), transition))
                }
            }

            Column(modifier = Modifier.width(360.dp)) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(16f / 9f)
                        .border(1.dp, Color.White.copy(alpha = 0.15f))
                ) {
                    DemoVisualizer(
                        effect = previewEffect,
                        pulse = viewModel.pulse,
                        beatClock = beatClock,
                        cover = art.cover,
                        palette = art.palette,
                        transition = transition,
                        modifier = Modifier.fillMaxSize()
                    )
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    buildString {
                        append(previewEffect.label)
                        append(if (previewEffect in COVER_EFFECTS) " · built from the cover" else " · cover colours")
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
            ChipButton("All") { viewModel.setAmbientEffects(DemoEffect.entries.toSet()) }
            Spacer(Modifier.width(8.dp))
            ChipButton("No cover art") {
                viewModel.setAmbientEffects(DemoEffect.entries.toSet() - COVER_EFFECTS)
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            DemoEffect.entries.chunked(CARDS_PER_ROW).forEach { rowEffects ->
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    rowEffects.forEachIndexed { index, effect ->
                        EffectCard(
                            effect = effect,
                            on = effect in enabled,
                            onFocused = { previewEffect = effect },
                            onClick = { viewModel.toggleAmbientEffect(effect) },
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
            .height(34.dp)
            .background(CardFill, RowShape)
            .tvFocusHighlight(RowShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(title, style = MaterialTheme.typography.bodyMedium, color = Color.White, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.labelLarge, color = ZonikColors.gold)
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
    Column(
        modifier = modifier
            .height(44.dp)
            .background(fill, RowShape)
            .onFocusChanged { if (it.isFocused) onFocused() }
            .tvFocusHighlight(RowShape)
            .clickable(onClick = onClick)
            .padding(horizontal = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            effect.label,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
            color = if (on) Color.White else Color.White.copy(alpha = 0.28f),
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis
        )
        if (effect in COVER_EFFECTS) {
            Text(
                "cover art",
                style = MaterialTheme.typography.labelSmall,
                color = Color.White.copy(alpha = if (on) 0.7f else 0.2f)
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
            .background(CardFill, RoundedCornerShape(50))
            .tvFocusHighlight(RoundedCornerShape(50))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp)
    )
}

private val DELAY_STEPS = listOf(0, 10, 30, 60, 90, 300)
private val ROTATE_STEPS = listOf(0, 30, 60, 120, 300)
private val INFO_LABELS = linkedMapOf(
    "FADE" to "Show, then fade",
    "ALWAYS" to "Always",
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
