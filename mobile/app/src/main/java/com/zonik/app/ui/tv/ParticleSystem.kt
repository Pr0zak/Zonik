package com.zonik.app.ui.tv

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.drawscope.CanvasDrawScope
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.Canvas as GraphicsCanvas
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.graphics.BlendMode
import kotlinx.coroutines.delay

enum class ParticleShape { ORB, RING, SPARKLE }

/** Which part of the music a given particle answers to. */
private enum class Band { LOW, MID, HIGH }

private class Particle(
    var x: Float, var y: Float,
    var dx: Float, var dy: Float,
    var baseRadius: Float,
    var color: Color,
    var shape: ParticleShape,
    var band: Band,
    var alpha: Float,
)

private fun createParticles(colors: List<Color>): List<Particle> {
    val shapes = ParticleShape.entries
    return List(30) { i ->
        val shape = shapes[i % 3]
        Particle(
            x = Math.random().toFloat(), y = Math.random().toFloat(),
            dx = (Math.random().toFloat() - 0.5f) * 0.0008f,
            dy = (Math.random().toFloat() - 0.5f) * 0.0008f,
            baseRadius = when (shape) {
                ParticleShape.ORB -> 12f + Math.random().toFloat() * 20f
                ParticleShape.RING -> 8f + Math.random().toFloat() * 16f
                ParticleShape.SPARKLE -> 3f + Math.random().toFloat() * 5f
            },
            color = colors[i % colors.size],
            shape = shape,
            // Big slow things answer the kick, small bright things answer the cymbals — so the
            // scene separates the way the music does instead of pulsing as one mass.
            band = when (shape) {
                ParticleShape.ORB -> Band.LOW
                ParticleShape.RING -> Band.MID
                ParticleShape.SPARKLE -> Band.HIGH
            },
            alpha = when (shape) {
                ParticleShape.ORB -> 0.10f + Math.random().toFloat() * 0.08f
                ParticleShape.RING -> 0.12f + Math.random().toFloat() * 0.10f
                ParticleShape.SPARKLE -> 0.18f + Math.random().toFloat() * 0.16f
            }
        )
    }
}

/**
 * The ambient particle field.
 *
 * Three things distinguish it from the version this replaces. Trails come from a feedback
 * buffer rather than from redrawing a list of past positions, so they last for seconds at a
 * fixed cost instead of eight blobs at 240 draw calls a frame. And particles are sized per
 * frequency band rather than by one loudness scalar.
 */
@Composable
fun ParticleSystem(
    pulse: AmbientPulse,
    anticipation: Float,
    colors: List<Color>,
    modifier: Modifier = Modifier,
) {
    val particles = remember(colors.hashCode()) { createParticles(colors) }
    var frameCounter by remember { mutableLongStateOf(0L) }
    var lastFrameTime by remember { mutableLongStateOf(System.nanoTime()) }

    // The feedback buffer. Everything is drawn into this, and each frame it is composited back
    // onto itself very slightly faded and scaled — which is what turns motion into a trail that
    // curls and lingers, for two full-buffer operations regardless of how long the trail is.
    var trailBuffer by remember { mutableStateOf<ImageBitmap?>(null) }

    LaunchedEffect(Unit) {
        while (true) {
            frameCounter++
            delay(33L)
        }
    }

    Canvas(modifier = modifier) {
        val now = System.nanoTime()
        val dt = ((now - lastFrameTime) / 1_000_000_000f).coerceIn(0f, 0.1f)
        lastFrameTime = now
        val w = size.width
        val h = size.height
        if (w < 1f || h < 1f) return@Canvas

        @Suppress("UNUSED_EXPRESSION")
        frameCounter

        val buffer = trailBuffer?.takeIf { it.width == w.toInt() && it.height == h.toInt() }
            ?: ImageBitmap(w.toInt().coerceAtLeast(1), h.toInt().coerceAtLeast(1))
                .also { trailBuffer = it }

        val bufferCanvas = GraphicsCanvas(buffer)
        // The fade IS the trail length: everything already in the buffer gets a little more
        // transparent each frame, so a particle leaves a tail that dies out over roughly a
        // second and a half.
        //
        // DstIn, not black-over. Painting translucent black on top fades the colour toward
        // black but drives the buffer's ALPHA toward opaque, so the layer turns into a solid
        // black sheet that hides whatever is drawn behind it — which is exactly what buried
        // the album-art background the first time. DstIn multiplies destination alpha by the
        // source's instead, which is a true fade-out.
        val fadePaint = Paint().apply {
            color = Color.Black.copy(alpha = 1f - TRAIL_FADE)
            blendMode = BlendMode.DstIn
        }
        bufferCanvas.drawRect(0f, 0f, w, h, fadePaint)

        val bufferScope = CanvasDrawScope()
        bufferScope.draw(this, layoutDirection, bufferCanvas, Size(w, h)) {
            drawParticles(particles, pulse, anticipation, dt, w, h)
        }

        drawImage(buffer)
    }
}

private fun DrawScope.drawParticles(
    particles: List<Particle>,
    pulse: AmbientPulse,
    anticipation: Float,
    dt: Float,
    w: Float,
    h: Float,
) {
    particles.forEach { p ->
        p.x += p.dx * dt * 60f
        p.y += p.dy * dt * 60f
        if (p.x < -0.05f) p.x += 1.1f
        if (p.x > 1.05f) p.x -= 1.1f
        if (p.y < -0.05f) p.y += 1.1f
        if (p.y > 1.05f) p.y -= 1.1f

        val level = when (p.band) {
            Band.LOW -> pulse.low
            Band.MID -> pulse.mid
            Band.HIGH -> pulse.high
        }
        // Anticipation swells everything slightly just BEFORE the grid's next beat, so motion
        // peaks on it rather than chasing it.
        val scale = 1f + level * 0.55f + anticipation * 0.12f
        val r = p.baseRadius * scale
        val cx = p.x * w
        val cy = p.y * h
        val a = (p.alpha * (0.7f + level * 0.6f)).coerceIn(0f, 1f)

        when (p.shape) {
            ParticleShape.ORB -> {
                // One soft halo, not the three stacked layers the old one drew — the overdraw
                // is what made a full-screen field expensive.
                drawCircle(p.color.copy(alpha = a * 0.35f), radius = r * 2.2f, center = Offset(cx, cy))
                drawCircle(p.color.copy(alpha = a), radius = r, center = Offset(cx, cy))
            }
            ParticleShape.RING -> drawCircle(
                p.color.copy(alpha = a), radius = r, center = Offset(cx, cy),
                style = Stroke(width = 1.5f + level * 2f)
            )
            ParticleShape.SPARKLE -> {
                val len = r * (1.4f + level * 1.6f)
                drawLine(p.color.copy(alpha = a), Offset(cx - len, cy), Offset(cx + len, cy), strokeWidth = 1.4f)
                drawLine(p.color.copy(alpha = a), Offset(cx, cy - len), Offset(cx, cy + len), strokeWidth = 1.4f)
            }
        }
    }
}

private const val TRAIL_FADE = 0.10f
