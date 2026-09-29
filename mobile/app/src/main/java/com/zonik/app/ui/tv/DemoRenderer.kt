package com.zonik.app.ui.tv

import android.graphics.Bitmap
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.GLUtils
import androidx.compose.ui.graphics.Color
import com.zonik.app.data.DebugLog
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.sin

/**
 * Draws the [DemoEffect]s on the GL thread.
 *
 * Every effect is compiled when the surface is created, so switching is instant: setting
 * [effect] fades the current one to black, swaps, and fades the new one in — the hard cut of a
 * demo changing parts, not a blend, because blending two effects would double the GPU's work.
 *
 * Everything the UI hands over — the latest audio pulse, the beat clock, the cover and its
 * colours — goes through volatile fields and is picked up at the start of the next frame, so
 * the music never causes a recomposition and the GL thread never waits on the main thread.
 *
 * The audio arrives about 20 times a second. Drawing it as it lands makes the visuals step;
 * instead each frame eases toward the latest capture, which is what makes the motion glide.
 */
class DemoRenderer(initial: DemoEffect) : GLSurfaceView.Renderer {

    @Volatile var effect: DemoEffect = initial
    @Volatile var pulse: AmbientPulse = AmbientPulse()
    @Volatile var beatClock: BeatClock? = null
    @Volatile private var pendingCover: Bitmap? = null
    @Volatile private var palette: FloatArray = paletteOf(DEFAULT_PALETTE)

    /** What the walls are made of, kept so a recreated GL context can upload it again. */
    @Volatile private var cover: Bitmap? = null
    @Volatile private var paletteColors: List<Color> = DEFAULT_PALETTE

    fun setCover(bitmap: Bitmap?) {
        cover = bitmap
        pendingCover = bitmap ?: fallbackTexture(paletteColors)
    }

    fun setPalette(colors: List<Color>) {
        paletteColors = colors
        palette = paletteOf(colors)
        // Without a cover the walls are drawn from the palette, so keep them in step.
        if (cover == null) pendingCover = fallbackTexture(colors)
    }

    private class Program(val id: Int, val uniforms: Map<String, Int>, val aPos: Int)

    private val programs = HashMap<DemoEffect, Program>()
    private var current = initial
    /** 1 while an effect is showing; ramps to 0 and back when [effect] changes. */
    private var fade = 0f
    private var texture = 0
    private lateinit var quad: FloatBuffer
    private var aspect = 16f / 9f

    // Smoothed audio, eased toward [pulse] every frame.
    private var low = 0f
    private var mid = 0f
    private var high = 0f
    private var kick = 0f
    private var lastOnset = 0f

    // Motion integrators. Wrapped into 0..2 (the mirrored texture's period) so precision holds
    // however long the screen is up.
    private var phase = 0f
    private var spin = 0f
    private var time = 0f
    private var clock = 0.0

    // Kicks counted so the kaleidoscope can change its wedge count every few bars.
    private var kickCount = 0
    private val balls = FloatArray(15)

    private var lastFrameNs = 0L
    private var fpsWindowStartNs = 0L
    private var fpsFrames = 0

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        programs.clear()
        for (e in DemoEffect.entries) {
            val id = buildProgram(DEMO_VERTEX, e.fragmentShader, e)
            // A uniform an effect does not use is compiled out and reports -1; skipped below.
            val locations = UNIFORM_NAMES.associateWith { GLES20.glGetUniformLocation(id, it) }
            programs[e] = Program(id, locations, GLES20.glGetAttribLocation(id, "aPos"))
        }
        fade = 0f

        quad = ByteBuffer.allocateDirect(QUAD.size * 4).order(ByteOrder.nativeOrder())
            .asFloatBuffer().apply { put(QUAD); position(0) }

        val ids = IntArray(1)
        GLES20.glGenTextures(1, ids, 0)
        texture = ids[0]
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture)
        // Mirrored, so the cover's left edge meets its own left edge on the tunnel wall rather
        // than a hard seam where it wraps. No mipmaps: at the vanishing point they would jump a
        // level along the atan seam and draw a line, and the fog hides the shimmer anyway.
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_MIRRORED_REPEAT)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_MIRRORED_REPEAT)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        // A new EGL context has lost any texture uploaded to the old one.
        pendingCover = cover ?: fallbackTexture(paletteColors)

        lastFrameNs = 0L
        fpsWindowStartNs = 0L
        fpsFrames = 0
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        GLES20.glViewport(0, 0, width, height)
        aspect = width.toFloat() / height.coerceAtLeast(1)
    }

    override fun onDrawFrame(gl: GL10?) {
        val now = System.nanoTime()
        val dt = if (lastFrameNs == 0L) 1f / 60f else ((now - lastFrameNs) / 1e9f).coerceIn(0f, 0.1f)
        lastFrameNs = now
        logFps(now)

        pendingCover?.let { uploadCover(it) }
        advance(dt)

        val requested = effect
        if (requested != current) {
            fade -= dt * FADE_RATE
            if (fade <= 0f) {
                fade = 0f
                current = requested
                DebugLog.d("DemoRenderer", "Effect -> ${current.name}")
            }
        } else {
            fade = (fade + dt * FADE_RATE).coerceAtMost(1f)
        }

        val prog = programs[current] ?: return
        uniforms = prog.uniforms
        GLES20.glUseProgram(prog.id)
        val drift = clock * 0.1
        u1("uAspect", aspect)
        u2("uCenter", (sin(drift * 3.7) * 0.12).toFloat(), (sin(drift * 2.9 + 1.3) * 0.08).toFloat())
        u1("uPhase", phase)
        u1("uSpin", spin)
        u1("uTime", time)
        u1("uFade", fade)
        u1("uSegments", SEGMENTS[(kickCount / KICKS_PER_SEGMENT_CHANGE) % SEGMENTS.size])
        uniforms["uBalls"]?.let { if (it >= 0) GLES20.glUniform3fv(it, 5, balls, 0) }
        u1("uTwist", (sin(drift * 1.3) * 0.06).toFloat() + mid * 0.05f)
        u1("uLow", low)
        u1("uMid", mid)
        u1("uHigh", high)
        u1("uKick", kick)
        u1("uBeat", beatClock?.anticipation(System.currentTimeMillis()) ?: 0f)
        val c = palette
        uniforms["uC0"]?.let { GLES20.glUniform3f(it, c[0], c[1], c[2]) }
        uniforms["uC1"]?.let { GLES20.glUniform3f(it, c[3], c[4], c[5]) }
        uniforms["uC2"]?.let { GLES20.glUniform3f(it, c[6], c[7], c[8]) }

        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture)
        uniforms["uTex"]?.let { GLES20.glUniform1i(it, 0) }

        GLES20.glEnableVertexAttribArray(prog.aPos)
        GLES20.glVertexAttribPointer(prog.aPos, 2, GLES20.GL_FLOAT, false, 0, quad)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
        GLES20.glDisableVertexAttribArray(prog.aPos)
    }

    /** Eases the audio toward the latest capture and moves the scene forward by [dt]. */
    private fun advance(dt: Float) {
        var target = pulse
        val grid = beatClock
        // No FFT (permission refused, or the device would not give a capture) but a known
        // tempo: synthesise a kick from the beat grid so the tunnel still moves in time.
        val silent = target.low == 0f && target.mid == 0f && target.high == 0f && target.onset == 0f
        if (silent && grid != null && grid.hasTempo) {
            val sinceBeat = grid.progressAt(System.currentTimeMillis())
            val hit = (1f - sinceBeat).let { it * it * it * it }
            target = AmbientPulse(low = hit * 0.7f, mid = 0.3f, high = 0.2f,
                onset = if (sinceBeat < 0.05f) 1f else 0f)
        }

        low = ease(low, target.low, dt)
        mid = ease(mid, target.mid, dt)
        high = ease(high, target.high, dt)

        // An onset is an event, so trigger on its rising edge and let it decay here at frame
        // rate rather than following the analyser's 20 Hz steps down.
        if (target.onset > 0.9f && lastOnset <= 0.9f) {
            kick = 1f
            kickCount++
        }
        lastOnset = target.onset
        kick *= exp(-dt * KICK_DECAY)

        // Bass is the throttle; the kick is a shove.
        val speed = CRUISE + low * 0.55f + kick * 0.9f
        phase = (phase + speed * dt) % WRAP
        spin = (spin + (0.012f + mid * 0.03f) * dt) % WRAP
        time = (time + TIME_RATE * dt) % WRAP
        clock += dt
        moveBalls()
    }

    /**
     * Lissajous paths for the metaballs, each at its own speed so they never settle into a
     * pattern. The first three are sized by bass, mids and highs; the other two just drift.
     */
    private fun moveBalls() {
        val t = clock * 0.25
        for (i in 0 until 5) {
            val k = i + 1.0
            balls[i * 3] = (sin(t * (0.61 + 0.13 * k) + k * 1.7) * aspect * 0.62).toFloat()
            balls[i * 3 + 1] = (cos(t * (0.47 + 0.11 * k) + k * 2.3) * 0.62).toFloat()
        }
        // Written in place: this runs every frame, and garbage is what makes a weak CPU stutter.
        balls[2] = 0.20f + low * 0.16f + kick * 0.06f
        balls[5] = 0.17f + mid * 0.12f
        balls[8] = 0.13f + high * 0.12f
        balls[11] = 0.15f
        balls[14] = 0.12f
    }

    private fun ease(value: Float, target: Float, dt: Float): Float {
        val rate = if (target > value) ATTACK_RATE else RELEASE_RATE
        return value + (target - value) * (1f - exp(-dt * rate))
    }

    private fun uploadCover(source: Bitmap) {
        pendingCover = null
        // GLES 2 only repeats power-of-two textures, and 128 keeps the whole cover in GPU cache.
        val pot = if (source.width == TEX_SIZE && source.height == TEX_SIZE) source
        else Bitmap.createScaledBitmap(source, TEX_SIZE, TEX_SIZE, true)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture)
        GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, pot, 0)
    }

    private fun logFps(now: Long) {
        if (fpsWindowStartNs == 0L) fpsWindowStartNs = now
        fpsFrames++
        val elapsed = now - fpsWindowStartNs
        if (elapsed >= FPS_LOG_INTERVAL_NS) {
            val fps = fpsFrames * 1e9f / elapsed
            DebugLog.d("DemoRenderer", "${current.name} %.1f fps".format(fps))
            fpsWindowStartNs = now
            fpsFrames = 0
        }
    }

    /** The locations for whichever program is bound this frame. */
    private var uniforms: Map<String, Int> = emptyMap()

    private fun u1(name: String, value: Float) {
        uniforms[name]?.let { if (it >= 0) GLES20.glUniform1f(it, value) }
    }

    private fun u2(name: String, x: Float, y: Float) {
        uniforms[name]?.let { if (it >= 0) GLES20.glUniform2f(it, x, y) }
    }

    private fun buildProgram(vertex: String, fragment: String, e: DemoEffect): Int {
        val vs = compile(GLES20.GL_VERTEX_SHADER, vertex, e)
        val fs = compile(GLES20.GL_FRAGMENT_SHADER, fragment, e)
        val prog = GLES20.glCreateProgram()
        GLES20.glAttachShader(prog, vs)
        GLES20.glAttachShader(prog, fs)
        GLES20.glLinkProgram(prog)
        val status = IntArray(1)
        GLES20.glGetProgramiv(prog, GLES20.GL_LINK_STATUS, status, 0)
        if (status[0] == 0) {
            DebugLog.w("DemoRenderer", "${e.name} link failed: ${GLES20.glGetProgramInfoLog(prog)}")
        }
        return prog
    }

    private fun compile(type: Int, source: String, e: DemoEffect): Int {
        val shader = GLES20.glCreateShader(type)
        GLES20.glShaderSource(shader, source)
        GLES20.glCompileShader(shader)
        val status = IntArray(1)
        GLES20.glGetShaderiv(shader, GLES20.GL_COMPILE_STATUS, status, 0)
        if (status[0] == 0) {
            DebugLog.w("DemoRenderer", "${e.name} compile failed: ${GLES20.glGetShaderInfoLog(shader)}")
        }
        return shader
    }

    private companion object {
        const val TEX_SIZE = 128
        const val WRAP = 2f
        /** uTime's speed: one full cycle of the slow, music-independent drift every 40 s. */
        const val TIME_RATE = 0.05f
        const val FADE_RATE = 4f
        const val KICKS_PER_SEGMENT_CHANGE = 16
        val SEGMENTS = floatArrayOf(6f, 8f, 5f, 12f)
        const val CRUISE = 0.12f
        const val ATTACK_RATE = 30f
        const val RELEASE_RATE = 7f
        const val KICK_DECAY = 6f
        const val FPS_LOG_INTERVAL_NS = 10_000_000_000L

        val QUAD = floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f)

        val UNIFORM_NAMES = listOf(
            "uAspect", "uCenter", "uPhase", "uSpin", "uTime", "uTwist",
            "uLow", "uMid", "uHigh", "uKick", "uBeat", "uFade", "uSegments", "uBalls",
            "uC0", "uC1", "uC2", "uTex",
        )

        val DEFAULT_PALETTE = listOf(Color(0xFFE8B84A), Color(0xFF7C4DFF), Color(0xFF534AB7))

        fun paletteOf(colors: List<Color>): FloatArray {
            val c = if (colors.size >= 3) colors else DEFAULT_PALETTE
            return floatArrayOf(
                c[0].red, c[0].green, c[0].blue,
                c[1].red, c[1].green, c[1].blue,
                c[2].red, c[2].green, c[2].blue,
            )
        }

        /** Checkerboard in the palette, for a track with no cover. */
        fun fallbackTexture(colors: List<Color>): Bitmap {
            val c = if (colors.size >= 3) colors else DEFAULT_PALETTE
            val a = android.graphics.Color.argb(255, (c[1].red * 255).toInt(), (c[1].green * 255).toInt(), (c[1].blue * 255).toInt())
            val b = android.graphics.Color.argb(255, (c[2].red * 120).toInt(), (c[2].green * 120).toInt(), (c[2].blue * 120).toInt())
            val px = IntArray(TEX_SIZE * TEX_SIZE) { i ->
                val x = (i % TEX_SIZE) / 16
                val y = (i / TEX_SIZE) / 16
                if ((x + y) % 2 == 0) a else b
            }
            return Bitmap.createBitmap(px, TEX_SIZE, TEX_SIZE, Bitmap.Config.ARGB_8888)
        }
    }
}
