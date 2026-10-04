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
    /** Motion trails on every effect: each frame is laid over a faded copy of the last. */
    @Volatile var trails: Boolean = false
    @Volatile private var pendingTitle: android.graphics.Bitmap? = null
    /** Kept so a recreated GL context can draw the title again. */
    @Volatile private var titleText = ""
    /** A fixed wipe kind, or -1 to move through them. */
    @Volatile var transitionStyle: Int = -1
    /** How long a switch between effects takes; set from the TV Visualizer page. */
    @Volatile var transitionSec: Float = 1.6f
    /**
     * Where the effects' colours come from: "ALBUM" (the cover's palette), "RANDOM" (a fresh
     * vivid palette at every effect change), "CYCLE" (a vivid palette turning slowly round the
     * colour wheel) or "MIXED" (one of those three, picked at random for each effect). The
     * setting's own value, so the view passes it straight through.
     */
    @Volatile var colorMode: String = "ALBUM"
    private val cyclePalette = FloatArray(9)

    /** The colours one effect on screen is wearing: its resolved mode and, for RANDOM, its palette. */
    private class Look(val mode: String, val random: FloatArray)
    private var lookCurrent = Look("ALBUM", randomVividPalette())
    private var lookNext = lookCurrent
    /** Set while drawing the incoming effect of a transition, so it gets [lookNext]. */
    private var drawingIncoming = false

    private fun newLook(): Look {
        val mode = if (colorMode == "MIXED") LOOK_MODES[kotlin.random.Random.nextInt(LOOK_MODES.size)] else colorMode
        return Look(mode, randomVividPalette())
    }
    @Volatile var pulse: AmbientPulse = AmbientPulse()
    @Volatile var beatClock: BeatClock? = null
    @Volatile private var pendingCover: Bitmap? = null
    @Volatile private var palette: FloatArray = paletteOf(DEFAULT_PALETTE)
    /** How much rainbow colorAt() mixes in: none for a colourful cover, some for a grey one. */
    @Volatile private var rainbow: Float = rainbowFor(paletteOf(DEFAULT_PALETTE))

    /** What the walls are made of, kept so a recreated GL context can upload it again. */
    @Volatile private var cover: Bitmap? = null
    @Volatile private var paletteColors: List<Color> = DEFAULT_PALETTE

    fun setCover(bitmap: Bitmap?) {
        cover = bitmap
        pendingCover = bitmap ?: fallbackTexture(paletteColors)
    }

    /**
     * The track title, drawn white on transparent into a texture for the sine scroller. Built
     * here on the caller's thread (a one-line Canvas draw) and uploaded on the GL thread.
     */
    fun setTitle(text: String) {
        titleText = text
        val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
            color = android.graphics.Color.WHITE
            textSize = TITLE_TEXT_PX
            typeface = android.graphics.Typeface.DEFAULT_BOLD
        }
        val label = text.ifBlank { "Zonik" }.take(80)
        val width = (paint.measureText(label) + TITLE_TEXT_PX).toInt().coerceIn(64, 4096)
        val height = (TITLE_TEXT_PX * 1.5f).toInt()
        val bitmap = android.graphics.Bitmap.createBitmap(width, height, android.graphics.Bitmap.Config.ARGB_8888)
        android.graphics.Canvas(bitmap).drawText(label, TITLE_TEXT_PX / 2f, TITLE_TEXT_PX * 1.1f, paint)
        pendingTitle = bitmap
    }

    fun setPalette(colors: List<Color>) {
        paletteColors = colors
        palette = paletteOf(colors)
        rainbow = rainbowFor(palette)
        // Without a cover the walls are drawn from the palette, so keep them in step.
        if (cover == null) pendingCover = fallbackTexture(colors)
    }

    private class Program(val id: Int, val uniforms: Map<String, Int>, val aPos: Int)

    /** An offscreen colour buffer: a texture and the framebuffer that draws into it. */
    private class Target(val fbo: Int, val tex: Int)

    /**
     * Feedback for one effect on screen: the frame it drew last, and the one it is drawing.
     * Two of these, so a feedback effect sliding in during a transition does not scribble over
     * the one sliding out.
     */
    private class Slot(var prev: Target, var next: Target) {
        fun swap() { val t = prev; prev = next; next = t }
    }

    private var blit: Program? = null
    private var trailsProgram: Program? = null
    private var scratch: Target? = null
    private var slotCurrent: Slot? = null
    private var slotNext: Slot? = null
    /** Scale the blit samples its source at: 0.5 when a halfRes effect filled a quarter of it. */
    private var blitScale = 1f
    private var surfaceWidth = 1
    private var surfaceHeight = 1

    private var waveTexture = 0
    private val waveBytes = ByteBuffer.allocateDirect(WAVEFORM_POINTS)
    private var titleTexture = 0
    private var titleAspect = 4f

    private val programs = HashMap<DemoEffect, Program>()

    private var current = initial
    /** Fade-in from black when the surface first appears. */
    private var fade = 0f

    // The effect being transitioned to, how far along (0..1), which wipe shape, and how long
    // the switch has been waiting for a kick to land on.
    private var next: DemoEffect? = null
    private var transition = 0f
    private var wipeKind = 0
    private var waitedForBeat = 0f
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

    // The Mandelbrot dive: the target, how far it has dived (e-folds of magnification, which
    // grows without end), and the view that works out to once looped — see [advanceDive].
    private var zoomTarget: MandelTarget = MandelbrotTargets.random()
    private var zoomDepth = 0.0
    private var zoomScale = MANDEL_START_SCALE
    private var zoomTurn = 0.0
    private var zoomOnScreen = false
    private var zoomSinceTarget = 0f
    private var zoomFlash = 0f
    private var zoomFlashRising = false
    // Series skip for this frame (see [computeSkip]).
    private var skipCount = 0
    private var skipAr = 0.0
    private var skipAi = 0.0
    private var skipZr = 0.0
    private var skipZi = 0.0

    // The spectrum as drawn: eased toward each capture every frame, uploaded as a 64x1 texture.
    // Alpha carries each band's peak, which holds for a moment and then falls, for the
    // peak caps of the LED bars.
    private val spectrum = FloatArray(SPECTRUM_BANDS)
    private val peaks = FloatArray(SPECTRUM_BANDS)
    private val peakHold = FloatArray(SPECTRUM_BANDS)
    private val spectrumBytes = ByteBuffer.allocateDirect(SPECTRUM_BANDS * 2)
    private var spectrumTexture = 0

    // Shockwave rings: seconds since each was launched by a kick, or -1 when idle.
    private val ringAges = floatArrayOf(-1f, -1f, -1f, -1f)
    private var sinceKick = 0f

    // Where each shockwave ring's kick dropped into the water ripples (x, y per ring, in the
    // same units as `p`).
    private val dropPos = FloatArray(8)

    // The dot tunnel's rings — centre x, y and depth z each — the same for every pixel, so
    // worked out here once a frame rather than per pixel in the shader.
    private val tunnelRings = FloatArray(27)

    // Kicks counted so the kaleidoscope can change its wedge count every few bars.
    private var kickCount = 0
    /** Kicks since the last fps line, so a log shows whether the music is actually landing. */
    private var kicksLogged = 0
    /** The effect last counted as shown in [TvEffectStats]. */
    private var statsShown: DemoEffect? = null
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
        blit = buildPass(BLIT_FRAGMENT)
        trailsProgram = buildPass(TRAILS_FRAGMENT)
        // Buffers belonged to the old context; onSurfaceChanged makes new ones.
        scratch = null
        slotCurrent = null
        slotNext = null

        fade = 0f
        next = null

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
        uploadHeightmap()

        waveTexture = makeTexture(GLES20.GL_NEAREST)
        GLES20.glTexImage2D(
            GLES20.GL_TEXTURE_2D, 0, GLES20.GL_LUMINANCE, WAVEFORM_POINTS, 1, 0,
            GLES20.GL_LUMINANCE, GLES20.GL_UNSIGNED_BYTE, null
        )
        titleTexture = makeTexture(GLES20.GL_LINEAR)
        setTitle(titleText)

        GLES20.glGenTextures(1, ids, 0)
        spectrumTexture = ids[0]
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, spectrumTexture)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_NEAREST)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_NEAREST)
        GLES20.glTexImage2D(
            GLES20.GL_TEXTURE_2D, 0, GLES20.GL_LUMINANCE_ALPHA, SPECTRUM_BANDS, 1, 0,
            GLES20.GL_LUMINANCE_ALPHA, GLES20.GL_UNSIGNED_BYTE, null
        )

        // A new EGL context has lost any texture uploaded to the old one.
        pendingCover = cover ?: fallbackTexture(paletteColors)

        lastFrameNs = 0L
        fpsWindowStartNs = 0L
        fpsFrames = 0
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        GLES20.glViewport(0, 0, width, height)
        aspect = width.toFloat() / height.coerceAtLeast(1)
        surfaceWidth = width.coerceAtLeast(1)
        surfaceHeight = height.coerceAtLeast(1)
        listOfNotNull(scratch, slotCurrent?.prev, slotCurrent?.next, slotNext?.prev, slotNext?.next)
            .forEach { deleteTarget(it) }
        scratch = makeTarget()
        slotCurrent = Slot(makeTarget(), makeTarget())
        slotNext = Slot(makeTarget(), makeTarget())
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)
    }

    /** A CLAMP texture bound on the current unit, left bound for the caller to fill. */
    private fun makeTexture(filter: Int): Int {
        val ids = IntArray(1)
        GLES20.glGenTextures(1, ids, 0)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, ids[0])
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, filter)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, filter)
        return ids[0]
    }

    /** A surface-sized offscreen buffer, cleared to black. */
    private fun makeTarget(): Target {
        GLES20.glActiveTexture(GLES20.GL_TEXTURE7)
        val tex = makeTexture(GLES20.GL_LINEAR)
        GLES20.glTexImage2D(
            GLES20.GL_TEXTURE_2D, 0, GLES20.GL_RGB, surfaceWidth, surfaceHeight, 0,
            GLES20.GL_RGB, GLES20.GL_UNSIGNED_BYTE, null
        )
        val ids = IntArray(1)
        GLES20.glGenFramebuffers(1, ids, 0)
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, ids[0])
        GLES20.glFramebufferTexture2D(
            GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0, GLES20.GL_TEXTURE_2D, tex, 0
        )
        if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) != GLES20.GL_FRAMEBUFFER_COMPLETE) {
            DebugLog.w("DemoRenderer", "Offscreen buffer incomplete; feedback effects will not draw")
        }
        clearTarget(Target(ids[0], tex))
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        return Target(ids[0], tex)
    }

    private fun clearTarget(t: Target) {
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, t.fbo)
        GLES20.glClearColor(0f, 0f, 0f, 1f)
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT)
    }

    private fun deleteTarget(t: Target) {
        GLES20.glDeleteFramebuffers(1, intArrayOf(t.fbo), 0)
        GLES20.glDeleteTextures(1, intArrayOf(t.tex), 0)
    }

    private fun buildPass(fragment: String): Program {
        val id = buildProgram(DEMO_VERTEX, fragment, DemoEffect.TUNNEL)
        return Program(
            id,
            (UNIFORM_NAMES + listOf("uBlit", "uCur")).associateWith { GLES20.glGetUniformLocation(id, it) },
            GLES20.glGetAttribLocation(id, "aPos")
        )
    }

    override fun onDrawFrame(gl: GL10?) {
        val now = System.nanoTime()
        val dt = if (lastFrameNs == 0L) 1f / 60f else ((now - lastFrameNs) / 1e9f).coerceIn(0f, 0.1f)
        lastFrameNs = now
        logFps(now)

        pendingCover?.let { uploadCover(it) }
        advance(dt)
        uploadSpectrum()
        uploadWave()
        pendingTitle?.let { uploadTitle(it) }

        // Only fades in from black when the surface first appears; switching effects uses a
        // transition instead.
        fade = (fade + dt * FADE_RATE).coerceAtMost(1f)
        updateTransition(dt)

        val incoming = next
        if (current != statsShown) {
            statsShown = current
            TvEffectStats.shown(current)
        }
        if (incoming == null) {
            TvEffectStats.frame(current, dt)
            draw(current, wipe = -1f, incomingSide = false)
        } else {
            // Each pixel belongs to exactly one of the two effects, so a transition costs the
            // same as a single effect — a crossfade would draw both everywhere and halve the
            // frame rate on the Chromecast for its whole length.
            draw(current, wipe = transition, incomingSide = false)
            draw(incoming, wipe = transition, incomingSide = true)
        }
    }

    /**
     * Starts a transition when [effect] changes, and runs it. The start waits for the next kick
     * (up to [BEAT_WAIT_SEC]) so the change lands on the music rather than at an arbitrary
     * moment.
     */
    private fun updateTransition(dt: Float) {
        val incoming = next
        if (incoming != null) {
            transition += dt / transitionSec.coerceAtLeast(0.1f)
            if (transition >= 1f) {
                current = incoming
                lookCurrent = lookNext
                next = null
                // The incoming effect's feedback becomes the current one's.
                val done = slotNext
                slotNext = slotCurrent
                slotCurrent = done
                DebugLog.d("DemoRenderer", "Effect -> ${current.name}")
            }
            return
        }
        val requested = effect
        if (requested == current) {
            waitedForBeat = 0f
            return
        }
        waitedForBeat += dt
        if (kick > 0.9f || waitedForBeat >= BEAT_WAIT_SEC || fade < 1f) {
            next = requested
            transition = 0f
            lookNext = newLook()
            waitedForBeat = 0f
            // A feedback effect coming in starts from black, not from the last one's leftovers.
            slotNext?.let { clearTarget(it.prev); clearTarget(it.next) }
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)
            val style = transitionStyle
            // "Mixed" picks at random, never the same wipe twice running.
            wipeKind = if (style in 0 until WIPE_KINDS) style
            else (wipeKind + 1 + kotlin.random.Random.nextInt(WIPE_KINDS - 1)) % WIPE_KINDS
        }
    }

    private fun draw(e: DemoEffect, wipe: Float, incomingSide: Boolean) {
        drawingIncoming = incomingSide
        val prog = programs[e] ?: return
        val slot = if (incomingSide) slotNext else slotCurrent
        val pass = scratch
        val scaler = blit
        val trailsPass = trailsProgram
        if (e.halfRes && !e.feedback && !trails && pass != null && scaler != null) {
            // Into the lower-left quarter of the scratch buffer, then scaled up by the blit.
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, pass.fbo)
            GLES20.glViewport(0, 0, surfaceWidth / 2, surfaceHeight / 2)
            drawWith(prog, e, -1f, false, 1f, prevTex = 0, srcTex = 0)
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)
            GLES20.glViewport(0, 0, surfaceWidth, surfaceHeight)
            blitScale = 0.5f
            drawWith(scaler, e, wipe, incomingSide, fade, prevTex = 0, srcTex = pass.tex)
            blitScale = 1f
            return
        }
        if (!(e.feedback || trails) || slot == null || pass == null || scaler == null || trailsPass == null) {
            drawWith(prog, e, wipe, incomingSide, fade, prevTex = 0, srcTex = 0)
            return
        }
        // Offscreen first, whole and unwiped; the blit to the screen applies the wipe and fade.
        if (e.feedback) {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, slot.next.fbo)
            drawWith(prog, e, -1f, false, 1f, prevTex = slot.prev.tex, srcTex = 0)
        } else {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, pass.fbo)
            drawWith(prog, e, -1f, false, 1f, prevTex = 0, srcTex = 0)
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, slot.next.fbo)
            drawWith(trailsPass, e, -1f, false, 1f, prevTex = slot.prev.tex, srcTex = pass.tex)
        }
        GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0)
        drawWith(scaler, e, wipe, incomingSide, fade, prevTex = 0, srcTex = slot.next.tex)
        slot.swap()
    }

    private fun drawWith(
        prog: Program, e: DemoEffect, wipe: Float, incomingSide: Boolean, fadeValue: Float,
        prevTex: Int, srcTex: Int,
    ) {
        uniforms = prog.uniforms
        GLES20.glUseProgram(prog.id)
        val drift = clock * 0.1
        u1("uAspect", aspect)
        u2("uCenter", (sin(drift * 3.7) * 0.12).toFloat(), (sin(drift * 2.9 + 1.3) * 0.08).toFloat())
        if (e.floats) {
            // A slow, gentle figure-eight with a second, slower term so the path never quite
            // repeats: about 90 s across and back, and never more than about a sixth of the
            // screen off centre. Wider than tall, since the title and progress sit along the
            // bottom and a framed cover must not drift under them.
            u2(
                "uFloat",
                (sin(clock * 0.07) * 0.3 + sin(clock * 0.029 + 2.0) * 0.05).toFloat(),
                (sin(clock * 0.053 + 1.1) * 0.12).toFloat()
            )
        } else {
            u2("uFloat", 0f, 0f)
        }
        u1("uPhase", phase)
        u1("uSpin", spin)
        u1("uTime", time)
        u1("uFade", fadeValue)
        u1("uWipe", wipe)
        u2("uPx", 1f / surfaceWidth, 1f / surfaceHeight)
        u1("uBlitScale", blitScale)
        val look = if (drawingIncoming) lookNext else lookCurrent
        u1("uRainbow", if (look.mode == "ALBUM") rainbow else 0f)
        u1("uTitleAspect", titleAspect)
        u1("uWipeSide", if (incomingSide) 1f else 0f)
        u1("uWipeKind", wipeKind.toFloat())
        if (e == DemoEffect.MANDELBROT) {
            val t = zoomTarget
            uniforms["uZoomCenter"]?.let { if (it >= 0) GLES20.glUniform2f(it, t.cRe.toFloat(), t.cIm.toFloat()) }
            val angle = zoomTurn + spin * Math.PI
            u2("uZoomRot", kotlin.math.cos(angle).toFloat(), kotlin.math.sin(angle).toFloat())
            u1("uZoomScale", zoomScale.toFloat())
            u1("uZoomFlash", zoomFlash)
            u1("uPre", t.preperiod.toFloat())
            u1("uPer", t.period.toFloat())
            val c = t.cycle
            u2("uCyc0", c[0], c[1])
            u2("uCyc1", c.getOrElse(2) { c[0] }, c.getOrElse(3) { c[1] })
            u2("uCyc2", c.getOrElse(4) { c[0] }, c.getOrElse(5) { c[1] })
            u1("uSkip", skipCount.toFloat())
            u2("uA", skipAr.toFloat(), skipAi.toFloat())
            u2("uZ0", skipZr.toFloat(), skipZi.toFloat())
        }
        u1("uSegments", SEGMENTS[(kickCount / KICKS_PER_SEGMENT_CHANGE) % SEGMENTS.size])
        u1("uKicks", (kickCount % 256).toFloat())
        uniforms["uBalls"]?.let { if (it >= 0) GLES20.glUniform3fv(it, 5, balls, 0) }
        uniforms["uTunnel"]?.let { if (it >= 0) GLES20.glUniform3fv(it, 9, tunnelRings, 0) }
        u1("uTwist", (sin(drift * 1.3) * 0.06).toFloat() + mid * 0.05f)
        u1("uLow", low)
        u1("uMid", mid)
        u1("uHigh", high)
        u1("uKick", kick)
        u1("uBeat", beatClock?.anticipation(System.currentTimeMillis()) ?: 0f)
        val c = when (look.mode) {
            "RANDOM" -> look.random
            "CYCLE" -> cyclePalette
            else -> palette
        }
        uniforms["uC0"]?.let { GLES20.glUniform3f(it, c[0], c[1], c[2]) }
        uniforms["uC1"]?.let { GLES20.glUniform3f(it, c[3], c[4], c[5]) }
        uniforms["uC2"]?.let { GLES20.glUniform3f(it, c[6], c[7], c[8]) }

        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, texture)
        uniforms["uTex"]?.let { GLES20.glUniform1i(it, 0) }
        uniforms["uSpectrum"]?.let { if (it >= 0) GLES20.glUniform1i(it, 2) }
        uniforms["uWave"]?.let { if (it >= 0) GLES20.glUniform1i(it, 3) }
        uniforms["uHeight"]?.let { if (it >= 0) GLES20.glUniform1i(it, 1) }
        uniforms["uTitle"]?.let { if (it >= 0) GLES20.glUniform1i(it, 4) }
        if (prevTex != 0) {
            GLES20.glActiveTexture(GLES20.GL_TEXTURE5)
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, prevTex)
            uniforms["uPrev"]?.let { if (it >= 0) GLES20.glUniform1i(it, 5) }
        }
        if (srcTex != 0) {
            GLES20.glActiveTexture(GLES20.GL_TEXTURE6)
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, srcTex)
            uniforms["uBlit"]?.let { if (it >= 0) GLES20.glUniform1i(it, 6) }
            uniforms["uCur"]?.let { if (it >= 0) GLES20.glUniform1i(it, 6) }
        }
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        uniforms["uRings"]?.let { if (it >= 0) GLES20.glUniform4f(it, ringAges[0], ringAges[1], ringAges[2], ringAges[3]) }
        uniforms["uDrops"]?.let { if (it >= 0) GLES20.glUniform2fv(it, 4, dropPos, 0) }

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
            kick = maxOf(kick, 0.5f + 0.5f * target.strength)
            kickCount++
            kicksLogged++
            TvEffectStats.kick(current)
            launchRing()
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
        moveTunnel()
        // The setting changed while nothing was switching: apply it straight away (a MIXED
        // setting keeps whatever the effect on screen already wears).
        if (next == null && colorMode != "MIXED" && lookCurrent.mode != colorMode) {
            lookCurrent = newLook()
            lookNext = lookCurrent
        }
        if (lookCurrent.mode == "CYCLE" || lookNext.mode == "CYCLE") fillCyclePalette()
        advanceSpectrum(target, dt)
        advanceRings(dt)
        advanceDive(dt)
    }

    /**
     * The Mandelbrot dive. Each time the effect comes on screen it picks a fresh random point
     * and dives from the whole set down to [MANDEL_LOOP_SCALE]; from there it loops through one
     * step of the point's self-similarity — the magnification keeps growing, but at the end of
     * each loop the view (scale ÷ |λ|, turned by arg λ) is the picture it started from, so the
     * zoom never ends and the per-pixel work never grows. Every few minutes it cuts to another
     * random point through a white flash, landing on a kick.
     */
    private fun advanceDive(dt: Float) {
        val onScreen = current == DemoEffect.MANDELBROT || next == DemoEffect.MANDELBROT
        if (onScreen && !zoomOnScreen) {
            zoomTarget = MandelbrotTargets.random()
            zoomDepth = 0.0
            zoomSinceTarget = 0f
            zoomFlash = 0f
            zoomFlashRising = false
        }
        zoomOnScreen = onScreen
        if (!onScreen) return

        zoomDepth += (0.25f + low * 0.4f + kick * 0.3f) * dt
        zoomSinceTarget += dt
        if (!zoomFlashRising && zoomFlash == 0f && zoomSinceTarget > MANDEL_RETARGET_SEC &&
            (kick > 0.9f || zoomSinceTarget > MANDEL_RETARGET_SEC + BEAT_WAIT_SEC)
        ) {
            zoomFlashRising = true
        }
        if (zoomFlashRising) {
            zoomFlash += dt / 0.12f
            if (zoomFlash >= 1f) {
                // Hidden behind the flash: straight into the new point's loop, no second intro.
                zoomFlash = 1f
                zoomFlashRising = false
                zoomTarget = MandelbrotTargets.random()
                zoomDepth = MANDEL_LOOP_DEPTH
                zoomSinceTarget = 0f
            }
        } else {
            zoomFlash = (zoomFlash - dt / 0.6f).coerceAtLeast(0f)
        }

        if (zoomDepth <= MANDEL_LOOP_DEPTH) {
            zoomScale = MANDEL_START_SCALE * exp(-zoomDepth)
            zoomTurn = 0.0
        } else {
            val loops = (zoomDepth - MANDEL_LOOP_DEPTH) / kotlin.math.ln(zoomTarget.lambdaMag)
            val u = loops - kotlin.math.floor(loops)
            zoomScale = MANDEL_LOOP_SCALE * Math.pow(zoomTarget.lambdaMag, -u)
            zoomTurn = -u * zoomTarget.lambdaArg
        }
        computeSkip()
    }

    /**
     * Series approximation. While a pixel's difference from the reference orbit is tiny it grows
     * almost linearly — ε_n ≈ A_n·δ + B_n·δ², with A_{n+1} = 2·Z_n·A_n + 1 and
     * B_{n+1} = 2·Z_n·B_n + A_n², the same for every pixel — so run those iterations once here
     * and let the shader start from ε = A·δ. Stops as soon as the dropped B·δ² term could reach
     * [SKIP_TOLERANCE] of A·δ anywhere on screen. (Bounding |A·δ| itself instead is far too
     * strict: A grows by |λ| per cycle, and it stopped the skip after four steps.)
     */
    private fun computeSkip() {
        val t = zoomTarget
        // The farthest a pixel's δ reaches: the screen corner plus the centre wander.
        val maxDelta = zoomScale * (kotlin.math.hypot(aspect.toDouble(), 1.0) + 0.2)
        var zr = 0.0; var zi = 0.0
        var ar = 0.0; var ai = 0.0
        var br = 0.0; var bi = 0.0
        var n = 0
        while (n < MAX_SKIP) {
            val nar = 2 * (zr * ar - zi * ai) + 1
            val nai = 2 * (zr * ai + zi * ar)
            val nbr = 2 * (zr * br - zi * bi) + (ar * ar - ai * ai)
            val nbi = 2 * (zr * bi + zi * br) + 2 * ar * ai
            if (kotlin.math.hypot(nbr, nbi) * maxDelta > SKIP_TOLERANCE * kotlin.math.hypot(nar, nai)) break
            val next = n + 1
            val nzr: Double
            val nzi: Double
            if (next < t.preperiod) {
                nzr = zr * zr - zi * zi + t.cRe
                nzi = 2 * zr * zi + t.cIm
            } else {
                val j = (next - t.preperiod) % t.period
                nzr = t.cycle[j * 2].toDouble()
                nzi = t.cycle[j * 2 + 1].toDouble()
            }
            ar = nar; ai = nai; br = nbr; bi = nbi; zr = nzr; zi = nzi
            n = next
        }
        skipCount = n; skipAr = ar; skipAi = ai; skipZr = zr; skipZi = zi
    }

    /**
     * Eases the drawn spectrum toward the latest capture. With no capture at all there is still
     * something to draw: the three smoothed bands spread across the 64, with a slow ripple so
     * the bars are not a flat shelf.
     */
    private fun advanceSpectrum(target: AmbientPulse, dt: Float) {
        val captured = target.spectrum
        for (i in 0 until SPECTRUM_BANDS) {
            val goal = if (captured != null && captured.size == SPECTRUM_BANDS) {
                captured[i]
            } else {
                val t = i / (SPECTRUM_BANDS - 1f)
                val level = when {
                    t < 0.33f -> low
                    t < 0.7f -> mid
                    else -> high
                }
                (level * (0.6f + 0.4f * sin(i * 0.9f + clock.toFloat() * 3f))).coerceIn(0f, 1f)
            }
            spectrum[i] = ease(spectrum[i], goal, dt)
            if (spectrum[i] >= peaks[i]) {
                peaks[i] = spectrum[i]
                peakHold[i] = PEAK_HOLD_SEC
            } else if (peakHold[i] > 0f) {
                peakHold[i] -= dt
            } else {
                peaks[i] = maxOf(peaks[i] - PEAK_FALL_RATE * dt, spectrum[i])
            }
        }
    }

    /** Ages the shockwave rings; with no kicks for a while, launches one anyway. */
    private fun advanceRings(dt: Float) {
        sinceKick += dt
        if (sinceKick > RING_IDLE_SEC) launchRing()
        for (i in ringAges.indices) {
            if (ringAges[i] < 0f) continue
            ringAges[i] += dt
            if (ringAges[i] > RING_LIFE_SEC) ringAges[i] = -1f
        }
    }

    private fun launchRing() {
        sinceKick = 0f
        // Reuse an idle slot, else the oldest ring.
        var slot = ringAges.indexOfFirst { it < 0f }
        if (slot < 0) slot = ringAges.indices.maxBy { ringAges[it] }
        ringAges[slot] = 0f
        dropPos[slot * 2] = (kotlin.random.Random.nextFloat() * 2f - 1f) * aspect * 0.75f
        dropPos[slot * 2 + 1] = (kotlin.random.Random.nextFloat() * 2f - 1f) * 0.75f
    }

    /**
     * The latest captured waveform; without a capture, a sine shaped by the three bands so the
     * scope still breathes with the tempo grid.
     */
    private fun uploadWave() {
        val captured = pulse.waveform
        waveBytes.position(0)
        for (i in 0 until WAVEFORM_POINTS) {
            val v = if (captured != null && captured.size == WAVEFORM_POINTS) captured[i]
            else 0.5f + 0.35f * (low * sin(i * 0.15f + clock.toFloat() * 6f) +
                0.5f * mid * sin(i * 0.61f - clock.toFloat() * 9f)) / 1.5f
            waveBytes.put((v.coerceIn(0f, 1f) * 255f).toInt().toByte())
        }
        waveBytes.position(0)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE3)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, waveTexture)
        GLES20.glTexSubImage2D(
            GLES20.GL_TEXTURE_2D, 0, 0, 0, WAVEFORM_POINTS, 1,
            GLES20.GL_LUMINANCE, GLES20.GL_UNSIGNED_BYTE, waveBytes
        )
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
    }

    /**
     * The voxel landscape's terrain, built once: a tileable heightmap from sines whose
     * frequencies are whole numbers over the tile, so it repeats seamlessly in both directions.
     * Kept bound on texture unit 1, which nothing else uses. Sampling it costs the shader one
     * texture read per step where evaluating the sines cost six.
     */
    private fun uploadHeightmap() {
        val n = HEIGHTMAP_SIZE
        val raw = FloatArray(n * n)
        var lo = Float.MAX_VALUE
        var hi = -Float.MAX_VALUE
        val tau = (2 * Math.PI).toFloat()
        for (y in 0 until n) for (x in 0 until n) {
            val u = x / n.toFloat()
            val v = y / n.toFloat()
            val h = 0.6f * sin(tau * (u * 2f + sin(tau * v) * 0.3f)) * kotlin.math.cos(tau * v * 3f) +
                0.35f * sin(tau * (u * 5f + v * 4f)) +
                0.15f * sin(tau * (u * 11f - v * 7f)) +
                0.08f * sin(tau * (u * 23f + v * 17f))
            raw[y * n + x] = h
            if (h < lo) lo = h
            if (h > hi) hi = h
        }
        val bytes = ByteBuffer.allocateDirect(n * n)
        for (h in raw) bytes.put(((h - lo) / (hi - lo) * 255f).toInt().toByte())
        bytes.position(0)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE1)
        val ids = IntArray(1)
        GLES20.glGenTextures(1, ids, 0)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, ids[0])
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_REPEAT)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_REPEAT)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexImage2D(
            GLES20.GL_TEXTURE_2D, 0, GLES20.GL_LUMINANCE, n, n, 0,
            GLES20.GL_LUMINANCE, GLES20.GL_UNSIGNED_BYTE, bytes
        )
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
    }

    private fun uploadTitle(bitmap: android.graphics.Bitmap) {
        pendingTitle = null
        GLES20.glActiveTexture(GLES20.GL_TEXTURE4)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, titleTexture)
        GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, bitmap, 0)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        titleAspect = bitmap.width.toFloat() / bitmap.height
    }

    private fun uploadSpectrum() {
        spectrumBytes.position(0)
        for (i in 0 until SPECTRUM_BANDS) {
            spectrumBytes.put((spectrum[i].coerceIn(0f, 1f) * 255f).toInt().toByte())
            spectrumBytes.put((peaks[i].coerceIn(0f, 1f) * 255f).toInt().toByte())
        }
        spectrumBytes.position(0)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE2)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, spectrumTexture)
        GLES20.glTexSubImage2D(
            GLES20.GL_TEXTURE_2D, 0, 0, 0, SPECTRUM_BANDS, 1,
            GLES20.GL_LUMINANCE_ALPHA, GLES20.GL_UNSIGNED_BYTE, spectrumBytes
        )
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
    }

    /** Three vivid colours a third of the wheel apart, turning once every [CYCLE_SEC]. */
    private fun fillCyclePalette() {
        val base = ((clock / CYCLE_SEC) % 1.0).toFloat() * 360f
        for (i in 0 until 3) {
            hsvInto(cyclePalette, i * 3, (base + i * 120f + if (i == 2) -60f else 0f) % 360f, 0.85f, 1f)
        }
    }

    private fun moveTunnel() {
        val t = time * Math.PI
        for (j in 0 until 9) {
            val f = (j / 9f + phase * 0.5f) % 1f
            val z = maxOf(1f - f, 0.03f)
            tunnelRings[j * 3] = (sin(t * 2 + z * 4) * 0.35 * z).toFloat()
            tunnelRings[j * 3 + 1] = (cos(t * 4 + z * 3) * 0.35 * z).toFloat()
            tunnelRings[j * 3 + 2] = z
        }
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
            val extra = if (current == DemoEffect.MANDELBROT) " (skip $skipCount, |λ| %.1f)".format(zoomTarget.lambdaMag) else ""
            DebugLog.d("DemoRenderer", "${current.name} %.1f fps, %d kicks$extra".format(fps, kicksLogged))
            kicksLogged = 0
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
        /** The cover texture. 256 so the framing effects can show the cover itself crisply. */
        const val TEX_SIZE = 256
        const val WRAP = 2f
        /** uTime's speed: one full cycle of the slow, music-independent drift every 40 s. */
        const val TIME_RATE = 0.05f
        const val FADE_RATE = 4f
        const val BEAT_WAIT_SEC = 1.5f
        /** How many wipes `wipeMask` in DemoEffects knows; names in [DEMO_TRANSITIONS]. */
        val WIPE_KINDS = DEMO_TRANSITIONS.size
        const val KICKS_PER_SEGMENT_CHANGE = 16
        val SEGMENTS = floatArrayOf(6f, 8f, 5f, 12f)

        /** Half-height of the view at the top of a dive: the whole set on screen. */
        const val MANDEL_START_SCALE = 1.4
        /**
         * Where the self-similar loop runs. Deep enough that the similarity is exact to the eye
         * (it is only asymptotic), shallow enough that points still escape within 40 iterations.
         */
        const val MANDEL_LOOP_SCALE = 2e-5
        val MANDEL_LOOP_DEPTH = kotlin.math.ln(MANDEL_START_SCALE / MANDEL_LOOP_SCALE)
        /** How long one point is dived into before cutting to another. */
        const val MANDEL_RETARGET_SEC = 150f
        const val MAX_SKIP = 60
        const val RING_LIFE_SEC = 3f
        const val TITLE_TEXT_PX = 96f
        const val HEIGHTMAP_SIZE = 256
        const val RING_IDLE_SEC = 2.5f
        const val PEAK_HOLD_SEC = 0.6f
        val LOOK_MODES = arrayOf("ALBUM", "RANDOM", "CYCLE")
        /** One full turn of the colour wheel in Cycle mode. */
        const val CYCLE_SEC = 40.0

        private val hsvScratch = FloatArray(3)

        /** Writes the HSV colour as 0..1 RGB into [out] at [offset]. */
        fun hsvInto(out: FloatArray, offset: Int, hue: Float, sat: Float, value: Float) {
            hsvScratch[0] = hue; hsvScratch[1] = sat; hsvScratch[2] = value
            val c = android.graphics.Color.HSVToColor(hsvScratch)
            out[offset] = android.graphics.Color.red(c) / 255f
            out[offset + 1] = android.graphics.Color.green(c) / 255f
            out[offset + 2] = android.graphics.Color.blue(c) / 255f
        }

        /**
         * Three vivid colours from a random scheme: a base hue plus either its neighbours
         * (analogous), its opposite, or a triad — so a random palette still looks chosen.
         */
        fun randomVividPalette(): FloatArray {
            val rnd = kotlin.random.Random
            val base = rnd.nextFloat() * 360f
            val offsets = when (rnd.nextInt(3)) {
                0 -> floatArrayOf(0f, 35f, -35f)
                1 -> floatArrayOf(0f, 180f, 150f)
                else -> floatArrayOf(0f, 120f, 240f)
            }
            val out = FloatArray(9)
            for (i in 0 until 3) {
                hsvInto(out, i * 3, (base + offsets[i] + 360f) % 360f, 0.7f + rnd.nextFloat() * 0.3f, 0.85f + rnd.nextFloat() * 0.15f)
            }
            return out
        }
        const val PEAK_FALL_RATE = 0.7f
        const val SKIP_TOLERANCE = 1e-3

        const val CRUISE = 0.12f
        const val ATTACK_RATE = 30f
        const val RELEASE_RATE = 11f
        const val KICK_DECAY = 6f
        const val FPS_LOG_INTERVAL_NS = 10_000_000_000L

        val QUAD = floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f)

        val UNIFORM_NAMES = listOf(
            "uAspect", "uCenter", "uFloat", "uPhase", "uSpin", "uTime", "uTwist",
            "uLow", "uMid", "uHigh", "uKick", "uBeat", "uFade", "uSegments", "uBalls",
            "uWipe", "uWipeSide", "uWipeKind", "uZoomCenter", "uZoomScale", "uZoomRot", "uZoomFlash",
            "uPre", "uPer", "uCyc0", "uCyc1", "uCyc2", "uSkip", "uA", "uZ0",
            "uSpectrum", "uRings", "uWave", "uTitle", "uTitleAspect", "uPrev", "uPx", "uHeight", "uTunnel", "uBlitScale", "uRainbow", "uDrops", "uKicks",
            "uC0", "uC1", "uC2", "uTex",
        )

        val DEFAULT_PALETTE = listOf(Color(0xFFE8B84A), Color(0xFF7C4DFF), Color(0xFF534AB7))

        /**
         * The shader used to work this out per pixel: the first two swatches' saturation, and
         * the less there is, the more classic rainbow shows through (never more than 70%).
         */
        fun rainbowFor(p: FloatArray): Float {
            fun sat(o: Int) = maxOf(p[o], p[o + 1], p[o + 2]) - minOf(p[o], p[o + 1], p[o + 2])
            val coverWeight = ((sat(0) + sat(3)) * 2f).coerceIn(0.3f, 1f)
            return 1f - coverWeight
        }

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
