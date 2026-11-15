package com.zonik.app.ui.tv

import com.zonik.app.data.api.TrackBeatsResponse

/** What the TV visualizer takes from the server's beat grid and analysis for one track. */
data class TrackBeats(
    val trackId: String,
    /** Null when the track has no steady beat (or the server none): the tempo alone is used. */
    val grid: BeatGrid?,
    val key: String?,
    val scale: String?,
    val energy: Float?,
) {
    companion object {
        fun from(trackId: String, r: TrackBeatsResponse): TrackBeats {
            val grid = if (r.status == "ready" && r.bpm != null && r.downbeatS != null) {
                BeatGrid(r.bpm, r.downbeatS * 1000f, r.beatsPerBar ?: 4, r.drops, r.barEnergy)
            } else null
            return TrackBeats(trackId, grid, r.key, r.scale, r.energy)
        }
    }
}

/**
 * How the Journey's worlds look and move for one track, so each song gets its own route:
 * colours turned round the wheel by the key (along the circle of fifths, so related keys sit
 * near each other) plus a little of the track's own hash, wall thickness and bubble size from
 * the hash, flying speed from the analysed energy, and the order the worlds come in.
 */
data class JourneyLook(
    /** Added to every colour lookup; 0..1 is once round the wheel. */
    val hue: Float = 0f,
    /** 0..1: thicker walls, bigger bubbles and pillars. */
    val density: Float = 0f,
    /** Multiplies the flying speed. */
    val speed: Float = 1f,
    /** Seeds the order of the worlds. */
    val order: Int = 0,
) {
    companion object {
        private val SHARPS = listOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
        private val FLATS = mapOf("Db" to "C#", "Eb" to "D#", "Gb" to "F#", "Ab" to "G#", "Bb" to "A#")

        fun of(trackId: String, key: String?, scale: String?, energy: Float?): JourneyLook {
            val h = trackId.hashCode()
            val frac = { shift: Int -> ((h ushr shift) and 0xFF) / 255f }
            var hue = frac(0) * 0.12f
            val pitch = key?.let { SHARPS.indexOf(FLATS[it] ?: it) } ?: -1
            if (pitch >= 0) {
                // A minor key sits with its relative major, three semitones up.
                val major = if (scale == "minor") (pitch + 3) % 12 else pitch
                hue += ((major * 7) % 12) / 12f
            }
            return JourneyLook(
                hue = hue % 1f,
                density = frac(8) * 0.7f,
                speed = 0.8f + 0.5f * (energy ?: 0.4f).coerceIn(0f, 1f),
                order = h,
            )
        }
    }
}

/** The worlds the Journey flies through, in [DemoEffect] order. */
val JOURNEY_WORLDS: List<DemoEffect> = DemoEffect.entries.filter { it.world }

/**
 * The Journey's sequencer: which world it is in or flying to, when the next portal opens, and
 * the gate's distance ahead. Pure logic, driven once a frame by the renderer, so it can be
 * tested without a GL context.
 *
 * The next portal is planned as a beat number when there is a tempo, so a seek or a resync
 * moves it with the music, and as a wall-clock time when there is none:
 * - with a beat grid lined up to the player: the start of the next 32-beat phrase at least
 *   [MIN_WORLD_MS] away, or a drop if one lands in the [DROP_WINDOW_MS] after that;
 * - with only a tempo: a 16-beat boundary at least [FALLBACK_WORLD_MS] away;
 * - with neither: [FALLBACK_WORLD_MS], then the next kick (or [KICK_WAIT_MS] at most).
 * For the last bar before it (1.2 to 3 s), the gate is up and closing in, so the camera
 * passes through it as the portal opens.
 */
class JourneySequencer {
    /** The world to be in: the renderer flies to it whenever it differs from the one shown. */
    var world: DemoEffect? = null
        private set
    /** The gate's distance ahead in world units, or 0 when it is not up. */
    var gate = 0f
        private set

    private var targetBeat = Double.NaN
    private var targetMs = 0L
    private var plannedWith: BeatClock? = null
    private var plannedSynced = false
    private var planned = false

    fun reset() {
        world = null
        gate = 0f
        planned = false
        plannedWith = null
    }

    /**
     * One frame. [unitsPerSec] is how fast the camera is cruising (without kicks or bursts,
     * so the gate closes in smoothly); [transitioning] while a switch is running.
     */
    fun update(
        current: DemoEffect,
        worlds: List<DemoEffect>,
        order: Int,
        clock: BeatClock?,
        nowMs: Long,
        kick: Float,
        unitsPerSec: Float,
        transitioning: Boolean,
    ) {
        val ws = worlds.ifEmpty { JOURNEY_WORLDS }
        val w = world
        if (w == null || w !in ws) {
            world = if (current.world && current in ws) current else ordered(ws, order).first()
            planned = false
        }
        // The clock is rebuilt when a track's grid arrives and syncs a moment later: plan again
        // with the better one, unless the gate is already up.
        val clockChanged = clock !== plannedWith || (clock?.synced == true) != plannedSynced
        if (!planned || (clockChanged && gate == 0f)) plan(clock, nowMs)
        if (transitioning || ws.size < 2) {
            gate = 0f
            return
        }
        var left = msLeft(nowMs)
        if (left > MAX_PLAN_MS || left < -STALE_MS) {
            // A seek moved the music far from the plan.
            plan(clock, nowMs)
            left = msLeft(nowMs)
        }
        gate = if (left >= 0f && left <= gateLeadMs(clock)) left / 1000f * unitsPerSec else 0f
        if (left > 0f) return
        // Due. On a tempo the moment is the beat itself; without one, wait for a kick.
        val onBeat = clock?.hasTempo == true || kick > 0.9f || left < -KICK_WAIT_MS
        if (!onBeat) return
        val o = ordered(ws, order)
        world = o[(o.indexOf(world) + 1) % o.size]
        gate = 0f
        plan(clock, nowMs)
    }

    /** Milliseconds until the planned portal (negative once it is due). */
    fun msLeft(nowMs: Long): Float {
        val c = plannedWith
        return if (!targetBeat.isNaN() && c != null && c.hasTempo) {
            ((targetBeat - c.beatAt(nowMs)) * c.beatMs).toFloat()
        } else {
            (targetMs - nowMs).toFloat()
        }
    }

    private fun plan(clock: BeatClock?, nowMs: Long) {
        plannedWith = clock
        plannedSynced = clock?.synced == true
        planned = true
        targetBeat = Double.NaN
        val ms = when {
            clock != null && clock.synced ->
                clock.msToDrop(nowMs, MIN_WORLD_MS, MIN_WORLD_MS + DROP_WINDOW_MS)
                    ?: clock.msToNextMultiple(nowMs, PHRASE_BEATS, MIN_WORLD_MS)
            clock != null && clock.hasTempo -> clock.msToNextMultiple(nowMs, 16, FALLBACK_WORLD_MS)
            else -> FALLBACK_WORLD_MS
        }
        if (clock != null && clock.hasTempo) {
            targetBeat = Math.round(clock.beatAt(nowMs) + ms / clock.beatMs).toDouble()
        } else {
            targetMs = nowMs + ms.toLong()
        }
    }

    companion object {
        const val MIN_WORLD_MS = 20_000f
        const val DROP_WINDOW_MS = 30_000f
        const val FALLBACK_WORLD_MS = 24_000f
        const val PHRASE_BEATS = 32
        const val KICK_WAIT_MS = 1_500f
        /** A plan further off than any the rules make (20 s + 30 s + a slow phrase) is stale. */
        const val MAX_PLAN_MS = 90_000f
        const val STALE_MS = 3_000f

        /** One bar before the portal, between 1.2 and 3 seconds. */
        fun gateLeadMs(clock: BeatClock?): Float {
            val c = clock?.takeIf { it.hasTempo } ?: return 2_000f
            return (c.beatMs * c.beatsPerBar).coerceIn(1_200f, 3_000f)
        }

        /** The worlds in a track's order. */
        fun ordered(worlds: List<DemoEffect>, order: Int): List<DemoEffect> {
            val seed = order.toLong()
            return worlds.sortedBy { ((it.ordinal + 1) * 2654435761L xor seed) and 0xFFFFFL }
        }
    }
}

/**
 * The Journey's flight path over one wrap of the flight (6π of z), as the shader reads it from
 * a texture: a gentle weave in closed form plus a sideways offset per sample that turns add.
 *
 * A turn rewrites the path from a point well ahead of the camera ([SAFE_AHEAD], past the fog)
 * round to just behind it: the path swerves sharply to a new offset there and holds it, and
 * eases back to the old offset at the far end, so the ring stays continuous; that far end is
 * the next turn unless a newer one replaces it first. The part the camera can see is never
 * touched, so nothing on screen jumps.
 */
class JourneyPath(val size: Int = 256) {
    private val level = FloatArray(size)

    /** Bumped on every change, so the renderer knows to upload the texture again. */
    var version = 0
        private set

    fun sampleZ(i: Int): Double = (i + 0.5) / size * PERIOD

    /** The sideways offset at [z], linearly between samples, as the texture filter reads it. */
    fun levelAt(z: Double): Float {
        val f = wrap(z, PERIOD) / PERIOD * size - 0.5
        val i0 = kotlin.math.floor(f).toInt()
        val k = (f - i0).toFloat()
        val a = level[((i0 % size) + size) % size]
        val b = level[(((i0 + 1) % size) + size) % size]
        return a + (b - a) * k
    }

    fun xAt(z: Double): Float = (baseX(z) + levelAt(z)).toFloat()

    /** Sideways offset the path holds at the camera now. */
    fun levelNow(camZ: Double): Float = levelAt(camZ)

    /**
     * Swerves the path to [target] over [length] units starting at [startZ] (absolute z, any
     * wrap). False when the start is too close to the camera to be off screen, or too far.
     */
    fun turn(camZ: Double, startZ: Double, target: Float, length: Double = TURN_LENGTH): Boolean {
        val ahead = wrap(startZ - camZ, PERIOD)
        val end = PERIOD - SAFE_BEHIND
        if (ahead < SAFE_AHEAD || ahead > end - 2 * length) return false
        val from = levelAt(startZ)
        val back = levelAt(camZ + end)
        for (i in 0 until size) {
            val a = wrap(sampleZ(i) - camZ, PERIOD)
            if (a < ahead || a > end) continue
            val swerved = from + (target - from) * smooth((a - ahead) / length)
            level[i] = back + (swerved - back) * smooth((end - a) / length)
        }
        version++
        return true
    }

    /** Roll into the path's curve at the camera, in radians. */
    fun bankAt(camZ: Double): Float {
        val h = 0.6
        val curve = (xAt(camZ + h) - 2 * xAt(camZ) + xAt(camZ - h)) / (h * h)
        return (-curve * BANK_GAIN).toFloat().coerceIn(-MAX_BANK, MAX_BANK)
    }

    /** RGBA bytes for the texture: x and y each as 16 bits, high byte in R/G, low in B/A. */
    fun pack(out: java.nio.ByteBuffer) {
        out.position(0)
        for (i in 0 until size) {
            val z = sampleZ(i)
            val ux = encode(baseX(z) + level[i])
            val uy = encode(baseY(z))
            out.put((ux shr 8).toByte()).put((uy shr 8).toByte())
                .put((ux and 0xFF).toByte()).put((uy and 0xFF).toByte())
        }
        out.position(0)
    }

    companion object {
        val PERIOD = 6.0 * Math.PI
        /** The shader's `JRANGE`: path coordinates are packed as -RANGE..RANGE. */
        const val RANGE = 4.0
        /** Past the fog (5 units) plus a margin. */
        const val SAFE_AHEAD = 6.0
        /** Leaves the samples the camera's own position is filtered from alone. */
        const val SAFE_BEHIND = 0.4
        const val TURN_LENGTH = 1.6
        /** Turns keep the path within this far of the weave, so positions stay small. */
        const val MAX_LEVEL = 2.2f
        const val BANK_GAIN = 0.1
        const val MAX_BANK = 0.4f

        fun baseX(z: Double) = 0.7 * kotlin.math.sin(z / 3.0) + 0.2 * kotlin.math.sin(z)
        fun baseY(z: Double) = 0.5 * kotlin.math.cos(z / 3.0)

        private fun encode(v: Double): Int =
            kotlin.math.round((v / RANGE + 1.0) / 2.0 * 65535.0).toInt().coerceIn(0, 65535)

        private fun wrap(x: Double, m: Double) = ((x % m) + m) % m

        private fun smooth(x: Double): Float {
            val t = x.coerceIn(0.0, 1.0)
            return (t * t * (3 - 2 * t)).toFloat()
        }
    }
}

/**
 * How a Journey world changes over the song, once a frame on the CPU:
 * - a sharp turn of the path now and then: on a 16-beat boundary (skipping about half of
 *   them) with a tempo, or every 9-16 s without one, placed where the camera should be then;
 * - the colours turning a step round the wheel at every 16 beats ([hue]);
 * - each world fading between its two looks every 32 beats, half a phrase off the portals
 *   ([style]);
 * - the current bar's loudness from the beat grid ([energy], 0 without one);
 * - the camera banking into the path's curves ([bank]).
 */
class JourneyMotion(seed: Int = 1) {
    var hue = 0f
        private set
    var style = 0f
        private set
    var energy = 0f
        private set
    var bank = 0f
        private set

    private val random = kotlin.random.Random(seed)
    private var hueTarget = 0f
    private var styleTarget = 0f
    private var lastPhrase = Long.MIN_VALUE
    private var nextTurnAtMs = 0L

    fun update(clock: BeatClock?, nowMs: Long, dt: Float, camZ: Double, unitsPerSec: Float, path: JourneyPath) {
        // Phrases: 16 beats with a tempo, 20 s without.
        val phrase = if (clock != null && clock.hasTempo) {
            kotlin.math.floor(clock.beatAt(nowMs) / 16.0).toLong()
        } else {
            nowMs / 20_000L
        }
        if (phrase != lastPhrase) {
            if (lastPhrase != Long.MIN_VALUE) hueTarget += 0.12f + random.nextFloat() * 0.2f
            val m = ((phrase % 4) + 4) % 4
            styleTarget = if (m == 1L || m == 2L) 1f else 0f
            lastPhrase = phrase
        }
        hue += (hueTarget - hue) * (1f - kotlin.math.exp(-dt * 0.8f))
        style = if (style < styleTarget) (style + dt / STYLE_FADE_SEC).coerceAtMost(styleTarget)
        else (style - dt / STYLE_FADE_SEC).coerceAtLeast(styleTarget)
        val e = clock?.barEnergyAt(nowMs) ?: 0f
        energy += (e - energy) * (1f - kotlin.math.exp(-dt * 3f))
        bank += (path.bankAt(camZ) - bank) * (1f - kotlin.math.exp(-dt * 4f))

        if (nowMs >= nextTurnAtMs) planTurn(clock, nowMs, camZ, unitsPerSec, path)
    }

    private fun planTurn(clock: BeatClock?, nowMs: Long, camZ: Double, unitsPerSec: Float, path: JourneyPath) {
        val speed = unitsPerSec.coerceAtLeast(0.3f)
        // The turn's middle must be past the fog when it is placed.
        val minMs = ((JourneyPath.SAFE_AHEAD + JourneyPath.TURN_LENGTH) / speed * 1000.0).toFloat()
        var ms = if (clock != null && clock.hasTempo) {
            clock.msToNextMultiple(nowMs, 16, minMs).let {
                if (random.nextBoolean()) it + 16 * clock.beatMs else it
            }
        } else {
            maxOf(minMs, 9_000f + random.nextFloat() * 7_000f)
        }
        val middle = camZ + speed * ms / 1000.0
        val now = path.levelNow(camZ)
        var dir = if (random.nextBoolean()) 1f else -1f
        val size = 0.7f + random.nextFloat() * 0.7f
        if (kotlin.math.abs(now + dir * size) > JourneyPath.MAX_LEVEL) dir = -dir
        val placed = path.turn(camZ, middle - JourneyPath.TURN_LENGTH / 2, now + dir * size)
        if (!placed) ms = 4_000f // too far for this speed: look again shortly
        nextTurnAtMs = nowMs + ms.toLong() + 500L
    }

    private companion object {
        const val STYLE_FADE_SEC = 1.5f
    }
}
