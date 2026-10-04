package com.zonik.app.ui.tv

import android.graphics.Bitmap
import android.graphics.drawable.BitmapDrawable
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.palette.graphics.Palette
import coil.imageLoader
import coil.request.ImageRequest
import coil.request.SuccessResult
import com.zonik.app.ui.theme.ZonikColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** What the visualizer is dressed in for a track: its cover as a texture, and colours from it. */
data class AmbientArt(val cover: Bitmap?, val palette: List<Color>)

private val DEFAULT_AMBIENT_PALETTE = listOf(ZonikColors.gold, Color(0xFF7C4DFF), Color(0xFF534AB7))

/** The wipes the renderer can switch effects with, in `uWipeKind` order. */
val DEMO_TRANSITIONS = listOf(
    "Block dissolve", "Iris", "Clock sweep", "Ragged wipe", "Checkerboard",
    "Diamond", "Spiral", "Venetian blinds", "Split doors", "Radiating dissolve",
    "Melt", "Hexagons", "Shatter", "Star iris", "Wavy iris",
    "Pinwheel", "Rings", "Interlace", "Block cascade", "Burn",
)

/** Effects built on the cover image itself; the rest only take its colours. */
val COVER_EFFECTS = setOf(
    DemoEffect.TUNNEL, DemoEffect.ROTOZOOM, DemoEffect.KALEIDOSCOPE,
    DemoEffect.RIPPLES, DemoEffect.DEFORM, DemoEffect.VHS,
    DemoEffect.DROSTE, DemoEffect.MOSAIC, DemoEffect.SQUARETUNNEL, DemoEffect.BENTTUBE,
    DemoEffect.FLYINGCOVERS, DemoEffect.PLANET, DemoEffect.BUMP, DemoEffect.HALFTONE, DemoEffect.ASCII,
    DemoEffect.WARPTUNNEL, DemoEffect.KALEIDOZOOM, DemoEffect.DROSTESPIRAL, DemoEffect.TRITUNNEL,
    DemoEffect.OCTOTUNNEL, DemoEffect.COVERBOUNCE,
)

/**
 * Loads a track's cover small and samples colours from it, so a grunge sleeve and a synth sleeve
 * do not produce the identical scene. Falls back to the Zonik palette when there is no cover.
 */
@Composable
fun rememberAmbientArt(coverArt: String?): AmbientArt {
    val context = LocalContext.current
    var art by remember(coverArt) { mutableStateOf(AmbientArt(null, DEFAULT_AMBIENT_PALETTE)) }
    LaunchedEffect(coverArt) {
        val coverArtId = coverArt ?: return@LaunchedEffect
        val loaded = withContext(Dispatchers.IO) {
            try {
                // Small on purpose: it becomes a GPU texture. 256px is enough for the effects
                // that show the cover itself at the centre, and still sits in texture cache.
                val request = ImageRequest.Builder(context)
                    .data("http://localhost/rest/getCoverArt.view?id=$coverArtId&size=256")
                    .allowHardware(false)
                    .build()
                val bitmap = ((context.imageLoader.execute(request) as? SuccessResult)?.drawable
                    as? BitmapDrawable)?.bitmap ?: return@withContext null
                // Palette runs here, off the main thread, which is also where the media
                // session dispatches the remote's play/skip commands.
                val swatches = Palette.from(bitmap).generate()
                AmbientArt(
                    bitmap,
                    listOf(
                        Color(swatches.getVibrantColor(ZonikColors.gold.toArgb())),
                        Color(swatches.getLightMutedColor(0xFF7C4DFF.toInt())),
                        Color(swatches.getMutedColor(0xFF534AB7.toInt())),
                    )
                )
            } catch (_: Exception) {
                null
            }
        } ?: return@LaunchedEffect
        art = loaded
    }
    return art
}

/**
 * Taps the audio output for as long as the caller is on screen. Beat reactivity needs
 * RECORD_AUDIO, which is asked for once and never insisted upon: without it the visuals keep
 * time from the server's tempo instead.
 */
@Composable
fun AudioCaptureEffect(viewModel: TvViewModel) {
    val context = LocalContext.current
    val beatReactive by viewModel.ambientBeatReactive.collectAsState()
    val permissionLauncher = androidx.activity.compose.rememberLauncherForActivityResult(
        contract = androidx.activity.result.contract.ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) viewModel.startVisualizer() }

    LaunchedEffect(beatReactive) {
        if (!beatReactive) {
            viewModel.stopVisualizer()
            return@LaunchedEffect
        }
        val granted = androidx.core.content.ContextCompat.checkSelfPermission(
            context, android.Manifest.permission.RECORD_AUDIO
        ) == android.content.pm.PackageManager.PERMISSION_GRANTED
        if (granted) viewModel.startVisualizer()
        else permissionLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
    }
    DisposableEffect(Unit) {
        onDispose { viewModel.stopVisualizer() }
    }
}
