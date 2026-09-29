package com.zonik.app.ui.tv

import android.graphics.Bitmap
import android.opengl.GLSurfaceView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.flow.StateFlow

/**
 * A [DemoEffect] running full-screen on its own GL thread.
 *
 * The surface is fixed at 960x540 and the display hardware scales it up to the panel, so the
 * GPU shades a quarter of a 1080p frame's pixels — which is what lets the Chromecast's small
 * Mali hold 60 fps — and the slight softness is the look the old demos had anyway.
 *
 * [pulse] is collected here and handed straight to the renderer rather than read in
 * composition, so the music moves the picture without recomposing anything.
 */
@Composable
fun DemoVisualizer(
    effect: DemoEffect,
    pulse: StateFlow<AmbientPulse>,
    beatClock: BeatClock,
    cover: Bitmap?,
    palette: List<Color>,
    modifier: Modifier = Modifier,
    /** A fixed wipe from [DEMO_TRANSITIONS], or -1 to vary them. */
    transition: Int = -1,
    /** Shown by the sine scroller. */
    title: String = "",
    /** Motion trails on every effect. */
    trails: Boolean = false,
) {
    // One renderer for the life of the screen: changing [effect] fades between effects on the
    // same surface instead of tearing the GL context down.
    val renderer = remember { DemoRenderer(effect) }
    LaunchedEffect(renderer, effect) { renderer.effect = effect }
    LaunchedEffect(renderer, transition) { renderer.transitionStyle = transition }
    LaunchedEffect(renderer, title) { renderer.setTitle(title) }
    LaunchedEffect(renderer, trails) { renderer.trails = trails }

    LaunchedEffect(renderer, pulse, beatClock) {
        pulse.collect { p ->
            renderer.pulse = p
            // The server knows the tempo but not where the downbeat falls, so a detected
            // onset snaps the grid's phase into place.
            if (beatClock.hasTempo && p.onset > 0.9f) beatClock.alignTo(System.currentTimeMillis())
        }
    }
    LaunchedEffect(renderer, beatClock) { renderer.beatClock = beatClock }
    LaunchedEffect(renderer, palette) { renderer.setPalette(palette) }
    LaunchedEffect(renderer, cover) { renderer.setCover(cover) }

    // The GL view must hear pause/resume, or its render thread keeps drawing to a stopped window.
    val view = remember { arrayOfNulls<GLSurfaceView>(1) }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_PAUSE -> view[0]?.onPause()
                Lifecycle.Event.ON_RESUME -> view[0]?.onResume()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    AndroidView(
        modifier = modifier,
        factory = { context ->
            GLSurfaceView(context).apply {
                setEGLContextClientVersion(2)
                preserveEGLContextOnPause = true
                holder.setFixedSize(SURFACE_WIDTH, SURFACE_HEIGHT)
                setRenderer(renderer)
                renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
            }.also { view[0] = it }
        },
    )
}

private const val SURFACE_WIDTH = 960
private const val SURFACE_HEIGHT = 540
