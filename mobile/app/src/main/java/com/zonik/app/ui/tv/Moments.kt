package com.zonik.app.ui.tv

import kotlin.math.exp
import kotlin.math.floor

/**
 * Moments: short changes to how a scene looks or moves, a beat to a few bars long, that ease in
 * and back out. The music sets most of them off and a random timer the rest; one at a time.
 *
 * Subtle ones (every ten seconds or so at the normal rate): [HUE] swing round the colour
 * wheel, [BREATHE] light swelling with the bass, a [FOG] bank, film [GRAIN] and vignette,
 * [SLOWMO] for a couple of beats, and a [DAYNIGHT] flip of an open world's time of day.
 *
 * Striking ones (rarer, mostly on the music's big moments): a [GLIMPSE] of another world
 * through an iris that opens and closes again (sometimes all the way, a short visit), a
 * [GHOST] of one dissolved in for a beat, [BLUEPRINT] edges only, [THERMAL] and [XRAY]
 * palettes, [CRUNCH] into big pixels, a [STUTTER] of frozen half-beats before a drop, a
 * [REWIND] scratch back along the path, a [HYPER] punch of streaks into a drop, a [KALEIDO]
 * burst, colour [ISOLATE] down to one palette colour, and [UPSIDE] down for a phrase; and
 * (2026-11-20) subtle [RIPPLE], [NEONEDGE], [CRT] scanlines, cinematic [LETTERBOX], [SEPIA]
 * film and [TILT] shift, striking [SWIRL], [GLITCH], [COMIC] book, [ECHO], [HALFTONE],
 * [DOUBLE] vision and a four-way [SPLIT4].
 *
 * Music: a drop coming sets off a stutter or a hyperspace punch just before it, and the drop
 * itself a glimpse, blueprint, thermal or x-ray; a breakdown (a bar much quieter than the last)
 * a slow motion, fog or colour isolation; a run of kicks a pixel crunch or a ghost.
 *
 * The looks are drawn over the finished frame by the blit ([postKind], `uMoment`); speed, roll,
 * lens and sky come out as plain values for the renderer, and the glimpse and ghost as a wipe
 * amount it draws a second world with. Pure logic, no GL.
 */
class Moments(seed: Int = 61) {
    private val random = kotlin.random.Random(seed)

    var kind = NONE
        private set
    /** 0..1: how far in the moment is, eased in and out. */
    var env = 0f
        private set
    /** A random value per moment, 0..1 (hue swing's direction, the glimpse's world...). */
    var param = 0f
        private set
    /** For a glimpse: open part way (an iris window) or all the way (a short visit). */
    var reach = 0.45f
        private set

    private var t = 0f
    private var len = 0f
    private var attack = 0.2f
    private var release = 0.3f
    private var wait = 8f
    private var sinceEnd = 99f
    private var sinceStriking = 99f
    private var lastDropBar = Int.MIN_VALUE
    private var lastBar = Long.MIN_VALUE
    private var lastBarEnergy = -1f
    private var lowSlow = 0f
    private var lowFast = 0f
    private var kickTimes = FloatArray(8) { -99f }
    private var kickIdx = 0
    private var clock = 0f
    private var wasKick = false
    private var kicksBack = false
    private var beatSec = 0.5f
    private var beatPhase = 0f

    /** For tests: how many of each kind have started. */
    val started = IntArray(KINDS)

    fun update(
        dt: Float, beats: BeatClock?, nowMs: Long, low: Float, kick: Float, world: Boolean,
        mode: Int, rate: Int, glimpses: Boolean, busy: Boolean,
    ) {
        clock += dt
        val tempo = beats?.takeIf { it.hasTempo }
        if (tempo != null) {
            beatSec = tempo.beatMs / 1000f
            beatPhase = tempo.progressAt(nowMs)
        } else {
            beatPhase = (beatPhase + dt / beatSec) % 1f
        }
        lowSlow += (low - lowSlow) * (1f - exp(-dt / 4f))
        lowFast += (low - lowFast) * (1f - exp(-dt / 0.6f))
        if (kick > 0.8f && !wasKick) {
            val last = kickTimes[(kickIdx + kickTimes.size - 1) % kickTimes.size]
            // Kicks back after a break of two seconds or more: the next run counts.
            if (clock - last > 2f) kicksBack = true
            kickTimes[kickIdx] = clock
            kickIdx = (kickIdx + 1) % kickTimes.size
        }
        wasKick = kick > 0.8f

        // A drop two beats off cuts a subtle moment short, to make way for the drop's own.
        if (kind != NONE && kind !in STRIKING && mode >= 2 && tempo?.msToDrop(nowMs, 0f, tempo.beatMs * 2.5f) != null) {
            kind = NONE
            env = 0f
            sinceEnd = 99f
        }
        // The one under way.
        if (kind != NONE) {
            t += dt
            if (mode == 0 || (busy && kind in WORLD_ONLY) || (!world && kind in WORLD_ONLY)) t = maxOf(t, len - release)
            env = envelope()
            if (t >= len) {
                if (kind in STRIKING) sinceStriking = 0f
                kind = NONE
                env = 0f
                sinceEnd = 0f
            }
            return
        }
        sinceEnd += dt
        sinceStriking += dt
        if (mode == 0) return
        val scale = when (rate) { 0 -> 2f; 2 -> 0.5f; else -> 1f }
        val canStrike = mode >= 2 && sinceStriking > 12f * scale
        fun ok(k: Int) = (world || k !in WORLD_ONLY) && (glimpses || (k != GLIMPSE && k != GHOST)) && !(busy && k in WORLD_ONLY)

        // Music first: a drop, a breakdown or a run of kicks.
        if (sinceEnd > 1.5f) {
            val music = musicEvent(tempo, nowMs, scale)
            if (music != null && (music.first !in STRIKING || canStrike) && ok(music.first) && poolAllows(music.first, mode)) {
                start(music.first, music.second)
                return
            }
        }
        // Then the random timer, landing on a beat.
        wait -= dt
        if (wait > 0f || sinceEnd < 3f) return
        if (tempo != null && tempo.msToNextBeat(nowMs) > 70f) return
        val pool = when {
            mode == 1 -> SUBTLE
            mode == 3 -> STRIKING
            canStrike && random.nextFloat() < 0.3f -> STRIKING
            else -> SUBTLE
        }.filter { ok(it) && (it !in STRIKING || canStrike || mode == 3) }
        wait = (if (mode == 3) 16f else 11f) * scale * (0.7f + 0.6f * random.nextFloat())
        if (pool.isEmpty()) return
        val k = pool[random.nextInt(pool.size)]
        start(k, beatsOf(k))
    }

    private fun poolAllows(k: Int, mode: Int) = when (mode) {
        1 -> k in SUBTLE
        3 -> k in STRIKING
        else -> true
    }

    /** A kind and its length in beats for what the music is doing now, or null. */
    private fun musicEvent(tempo: BeatClock?, nowMs: Long, scale: Float): Pair<Int, Float>? {
        val grid = tempo?.grid
        if (tempo != null && grid != null && tempo.synced) {
            val beat = tempo.beatMs
            // A drop two beats off: stutter into it, or one beat off: a hyperspace punch.
            tempo.msToDrop(nowMs, beat * 2f - 40f, beat * 2f)?.let { if (random.nextBoolean()) return STUTTER to 1.9f }
            tempo.msToDrop(nowMs, beat - 40f, beat)?.let { return HYPER to 1.1f }
            if (tempo.msToDrop(nowMs, -150f, 0f) != null) {
                val bar = floor(tempo.beatAt(nowMs) / grid.beatsPerBar).toInt()
                if (bar != lastDropBar) {
                    lastDropBar = bar
                    if (random.nextFloat() < 0.6f) {
                        val drop = listOf(GLIMPSE, BLUEPRINT, THERMAL, XRAY, SWIRL, COMIC, HALFTONE, ECHO)
                        val k = drop[random.nextInt(drop.size)]
                        return k to beatsOf(k)
                    }
                }
            }
            // A breakdown: this bar much quieter than the one before.
            val bar = floor(tempo.beatAt(nowMs) / grid.beatsPerBar).toLong()
            if (bar != lastBar) {
                lastBar = bar
                val e = tempo.barEnergyAt(nowMs)
                val before = lastBarEnergy
                lastBarEnergy = e ?: -1f
                if (e != null && before >= 0.55f && e < 0.35f) {
                    val calm = listOf(SLOWMO, FOG, ISOLATE, SEPIA, LETTERBOX, TILT)
                    val k = calm[random.nextInt(calm.size)]
                    return k to beatsOf(k)
                }
            }
        } else if (lowSlow > 0.45f && lowFast < 0.15f) {
            // Without a grid: the bass fell away.
            lowSlow = lowFast
            val calm = listOf(SLOWMO, FOG, ISOLATE, SEPIA, LETTERBOX, TILT)
            val k = calm[random.nextInt(calm.size)]
            return k to beatsOf(k)
        }
        // Kicks coming back after a break: eight in under four and a half seconds.
        val oldest = kickTimes[kickIdx]
        if (kicksBack && clock - oldest < 4.5f) {
            kicksBack = false
            val run = listOf(CRUNCH, GHOST, GLITCH, DOUBLE, SPLIT4)
            val k = run[random.nextInt(run.size)]
            return k to beatsOf(k)
        }
        return null
    }

    private fun beatsOf(k: Int): Float = when (k) {
        HUE -> 8f; BREATHE -> 8f; FOG -> 8f; GRAIN -> 16f; SLOWMO -> 3f; DAYNIGHT -> 32f
        GLIMPSE -> 6f + 2f * random.nextInt(2); GHOST -> 2f; BLUEPRINT -> 4f; THERMAL -> 4f; XRAY -> 4f
        CRUNCH -> 4f; STUTTER -> 2f; REWIND -> 4f; HYPER -> 1f; KALEIDO -> 4f; ISOLATE -> 8f; UPSIDE -> 16f
        RIPPLE -> 4f; SWIRL -> 4f; GLITCH -> 2f; COMIC -> 8f; ECHO -> 4f; NEONEDGE -> 8f; CRT -> 16f
        HALFTONE -> 4f; DOUBLE -> 2f; SPLIT4 -> 4f; LETTERBOX -> 16f; SEPIA -> 16f; TILT -> 16f
        else -> 4f
    }

    private fun start(k: Int, beats: Float) {
        kind = k
        t = 0f
        len = (beats * beatSec).coerceIn(0.4f, 20f)
        param = random.nextFloat()
        reach = if (k == GLIMPSE && random.nextFloat() < 0.35f) 1f else 0.45f
        // Some snap in on the beat; the rest ease.
        val snap = k in SNAP
        attack = if (snap) 0.06f else len * 0.25f
        release = if (snap) minOf(0.25f, len * 0.3f) else len * 0.3f
        if (k == HYPER) { attack = len * 0.85f; release = len * 0.15f }
        started[k]++
        env = 0f
    }

    private fun envelope(): Float {
        val a = if (attack > 0f) (t / attack).coerceIn(0f, 1f) else 1f
        val r = if (release > 0f) ((len - t) / release).coerceIn(0f, 1f) else 1f
        val e = minOf(a, r)
        return e * e * (3f - 2f * e)
    }

    /** The flight's speed against normal: slower, in steps, or backwards. */
    val speedScale: Float get() = when (kind) {
        SLOWMO -> 1f - 0.72f * env
        STUTTER -> if (env > 0.2f) (if ((beatPhase * 2f) % 1f < 0.35f) 2.6f else 0f) else 1f
        REWIND -> 1f - 2.1f * env
        else -> 1f
    }

    /** Extra camera roll, radians. */
    val roll: Float get() = if (kind == UPSIDE) Math.PI.toFloat() * env else 0f

    /** Multiplies the focal length: the hyperspace punch widens the view. */
    val lens: Float get() = if (kind == HYPER) 1f - 0.4f * env else 1f

    /** Added to an open world's time of day (JourneyLook.sky, 0..3) while it flips. */
    val skyShift: Int get() = if (kind == DAYNIGHT && env > 0.5f) 2 else 0

    /** The look the blit draws (`uMoment.x`), 0 for none. */
    val postKind: Int get() = if (kind in 1..POST_LAST) kind else 0

    /** For a glimpse or ghost: how far to wipe to the other world, 0..1. */
    val reveal: Float get() = when (kind) {
        GLIMPSE -> env * reach
        GHOST -> env * 0.5f
        else -> 0f
    }

    companion object {
        const val NONE = 0
        // Drawn over the frame by the blit (uMoment.x): 1..POST_LAST.
        const val HUE = 1
        const val BREATHE = 2
        const val FOG = 3
        const val GRAIN = 4
        const val THERMAL = 5
        const val XRAY = 6
        const val BLUEPRINT = 7
        const val CRUNCH = 8
        const val KALEIDO = 9
        const val ISOLATE = 10
        const val HYPER = 11
        const val RIPPLE = 12
        const val SWIRL = 13
        const val GLITCH = 14
        const val COMIC = 15
        const val ECHO = 16
        const val NEONEDGE = 17
        const val CRT = 18
        const val HALFTONE = 19
        const val DOUBLE = 20
        const val SPLIT4 = 21
        const val LETTERBOX = 22
        const val SEPIA = 23
        const val TILT = 24
        const val POST_LAST = 24
        // Speed, camera and sky, on the CPU.
        const val SLOWMO = 25
        const val DAYNIGHT = 26
        const val GLIMPSE = 27
        const val GHOST = 28
        const val STUTTER = 29
        const val REWIND = 30
        const val UPSIDE = 31
        const val KINDS = 32

        val SUBTLE = listOf(HUE, BREATHE, FOG, GRAIN, SLOWMO, DAYNIGHT, RIPPLE, NEONEDGE, CRT, LETTERBOX, SEPIA, TILT)
        val STRIKING = listOf(
            GLIMPSE, GHOST, BLUEPRINT, THERMAL, XRAY, CRUNCH, STUTTER, REWIND, HYPER, KALEIDO, ISOLATE, UPSIDE,
            SWIRL, GLITCH, COMIC, ECHO, HALFTONE, DOUBLE, SPLIT4,
        )
        /** Only in a Journey world: they need another world, the path or the open sky. */
        val WORLD_ONLY = setOf(DAYNIGHT, GLIMPSE, GHOST, REWIND, UPSIDE, STUTTER)
        private val SNAP = setOf(BLUEPRINT, THERMAL, XRAY, CRUNCH, KALEIDO, STUTTER, GLITCH, SPLIT4, COMIC, HALFTONE, DOUBLE)

        val MODE_LABELS = listOf("Off", "Subtle", "Mixed", "Striking")
        val RATE_LABELS = listOf("Rare", "Normal", "Often")
    }
}
