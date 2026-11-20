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
    /** The style over a world: 0 as made, 1 duotone in the palette, 2 night. Picked anew at
     * each world (DemoRenderer.newLook, JourneyOptions.pickStyle). */
    val style: Int = 0,
    /** The light over an open world: 0 as made, 1 dawn, 2 dusk, 3 storm light (jSkyGrade). */
    val sky: Int = 0,
    /** Its weather (JourneyDirector.RAIN, SNOW, FOG or none), where the world allows it. */
    val weather: Int = 0,
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
 * Scenes the Journey can stop in for a phrase between two worlds (JourneySequencer.interludes):
 * the ones that are not a forward flight, so the break reads as a change of view.
 */
val JOURNEY_INTERLUDES: List<DemoEffect> = listOf(
    DemoEffect.TINYPLANET, DemoEffect.GALAXYORBIT, DemoEffect.SPECTRUMRIDGES, DemoEffect.ENDLESSZOOM,
    DemoEffect.SCULPTURE, DemoEffect.STORMSEA, DemoEffect.EQCITY,
)

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
 *
 * With [interludes], every [INTERLUDE_EVERY]th change stops in one of them for a phrase on the
 * way to the next world (no gate: those changes wipe rather than fly through a portal).
 */
class JourneySequencer {
    /** Scenes to stop in between worlds now and then; empty for none. */
    var interludes: List<DemoEffect> = emptyList()
    private var changes = 0
    private var interludeTurn = 0
    /** The world to go on to after the interlude on screen. */
    private var afterInterlude: DemoEffect? = null
    /** The next change goes to an interlude, so no gate goes up for it. */
    private var nextIsInterlude = false
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

    /** How long each world lasts against normal (JourneyOptions): phrases and minimums scale. */
    var lengthScale = 1f

    fun reset() {
        world = null
        afterInterlude = null
        nextIsInterlude = false
        changes = 0
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
        val inInterlude = afterInterlude != null && w != null && !w.world
        if (w == null || (w !in ws && !inInterlude)) {
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
        if (left > MAX_PLAN_MS * lengthScale || left < -STALE_MS) {
            // A seek moved the music far from the plan.
            plan(clock, nowMs)
            left = msLeft(nowMs)
        }
        val gateUp = !inInterlude && !nextIsInterlude
        gate = if (gateUp && left >= 0f && left <= gateLeadMs(clock)) left / 1000f * unitsPerSec else 0f
        if (left > 0f) return
        // Due. On a tempo the moment is the beat itself; without one, wait for a kick.
        val onBeat = clock?.hasTempo == true || kick > 0.9f || left < -KICK_WAIT_MS
        if (!onBeat) return
        val o = ordered(ws, order)
        if (inInterlude) {
            world = afterInterlude
            afterInterlude = null
        } else {
            val nextWorld = o[(o.indexOf(world) + 1) % o.size]
            if (nextIsInterlude && interludes.isNotEmpty()) {
                afterInterlude = nextWorld
                world = interludes[interludeTurn++ % interludes.size]
            } else {
                world = nextWorld
            }
            changes++
        }
        nextIsInterlude = afterInterlude == null && interludes.isNotEmpty() && (changes + 1) % INTERLUDE_EVERY == 0
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
        val minMs = MIN_WORLD_MS * lengthScale
        val phrase = (PHRASE_BEATS * lengthScale).toInt().coerceAtLeast(8)
        val ms = when {
            clock != null && clock.synced ->
                clock.msToDrop(nowMs, minMs, minMs + DROP_WINDOW_MS * lengthScale)
                    ?: clock.msToNextMultiple(nowMs, phrase, minMs)
            clock != null && clock.hasTempo -> clock.msToNextMultiple(nowMs, phrase / 2, FALLBACK_WORLD_MS * lengthScale)
            else -> FALLBACK_WORLD_MS * lengthScale
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
        /** Every this many world changes, one goes by way of an interlude. */
        const val INTERLUDE_EVERY = 3
        const val KICK_WAIT_MS = 1_500f
        /** A plan further off than any the rules make (20 s + 30 s + a slow phrase) is stale. */
        const val MAX_PLAN_MS = 90_000f
        const val STALE_MS = 3_000f

        /** One bar before the portal, between 1.2 and 3 seconds. */
        fun gateLeadMs(clock: BeatClock?): Float {
            val c = clock?.takeIf { it.hasTempo } ?: return 2_000f
            return (c.beatMs * c.beatsPerBar).coerceIn(1_200f, 3_000f)
        }

        /** The order value for "always the same order": the worlds as listed. */
        const val FIXED_ORDER = Int.MIN_VALUE

        /** The worlds in a track's order ([FIXED_ORDER]: as listed). */
        fun ordered(worlds: List<DemoEffect>, order: Int): List<DemoEffect> {
            if (order == FIXED_ORDER) return worlds
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
        /** Long enough to read as a swerve, not a jolt. */
        const val TURN_LENGTH = 2.4
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
        bank += (path.bankAt(camZ) - bank) * (1f - kotlin.math.exp(-dt * 2f))

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

/**
 * Places the Journey's landmarks along the route: up to [SLOTS] objects, each with a type,
 * size, position and spin of its own, handed to the shader as `uMarks` (see JOURNEY_BODY).
 *
 * Big structures come only in the open worlds: giant rings, tunnels and hollow spheres to fly
 * through, arches to pass under, monoliths and giant crystals to pass by. They are placed where
 * the camera should be at the next 16-beat boundary, or at a drop when one is coming (a tunnel
 * or a hollow sphere then, so the drop is the moment it flies in). The enclosed worlds have
 * none. (Small objects scattered along the route, and Megastructures' scenery, were removed in
 * app 1.62: the user did not like the look of them.)
 *
 * Everything is placed beyond the fog, so nothing pops in. Positions are measured along the
 * flight ([travel], which never wraps) and handed over as distances ahead of the camera. Each
 * landmark keeps to the path's line at its own z, eased, so when a turn rewrites the path ahead
 * the structures drift across to it instead of jumping.
 */
class JourneyLandmarks(seed: Int = 7) {
    private class Mark(
        val z: Double,
        val type: Int,
        val size: Float,
        /** Spin rate in radians per second, or a tunnel's half length. */
        val w: Float,
        val offX: Float,
        val offY: Float,
        val param: Float,
        val hue: Float,
    ) {
        var x = Float.NaN
        var y = 0f
        var spin = 0f
        val reach: Double get() = if (type == TUNNEL) w.toDouble() else size * 1.3 + 0.3
    }

    private val random = kotlin.random.Random(seed)
    private val marks = arrayOfNulls<Mark>(SLOTS)
    private var nextLargeZ = Double.NaN
    private var lastWorld: JourneyWorld? = null

    /** How many slots are in use (for tests). */
    val count: Int get() = marks.count { it != null }

    fun types(): List<Int> = marks.filterNotNull().map { it.type }

    /** For the tests: an open world (Canyon) or an enclosed lattice. */
    fun update(
        open: Boolean, travel: Double, camZ: Double, unitsPerSec: Float,
        clock: BeatClock?, nowMs: Long, dt: Float, path: JourneyPath,
    ) = update(
        if (open) JourneyWorld.of(DemoEffect.CANYON) else JourneyWorld.of(DemoEffect.GYROID),
        travel, camZ, unitsPerSec, clock, nowMs, dt, path,
    )

    fun update(
        world: JourneyWorld, travel: Double, camZ: Double, unitsPerSec: Float,
        clock: BeatClock?, nowMs: Long, dt: Float, path: JourneyPath,
    ) {
        val open = world.large.isNotEmpty()
        val spawn = world.spawn
        for (i in marks.indices) {
            val m = marks[i] ?: continue
            if (m.z + m.reach < travel - 1.0) marks[i] = null
        }
        if (world !== lastWorld) {
            // A new world: what the last one placed further ahead does not belong in it.
            if (lastWorld != null) for (i in marks.indices) if ((marks[i]?.z ?: 0.0) > travel + 4.0) marks[i] = null
            lastWorld = world
            nextLargeZ = Double.NaN
        }
        if (!open) {
            nextLargeZ = Double.NaN
        } else {
            val speed = unitsPerSec.coerceAtLeast(0.3f)
            if (nextLargeZ.isNaN()) nextLargeZ = travel + spawn
            if (travel + spawn >= nextLargeZ) {
                val mark = large(world.large, travel, spawn, speed, clock, nowMs)
                if (add(mark)) nextLargeZ = mark.z + mark.reach + speed * (2f + random.nextFloat() * 3f)
            }
        }
        for (m in marks) {
            m ?: continue
            val along = camZ + (m.z - travel)
            val tx = path.xAt(along) + m.offX
            val ty = JourneyPath.baseY(along).toFloat() + m.offY
            if (m.x.isNaN()) {
                m.x = tx
                m.y = ty
            } else {
                val k = 1f - kotlin.math.exp(-dt * 1.5f)
                m.x += (tx - m.x) * k
                m.y += (ty - m.y) * k
            }
            if (m.type != TUNNEL) m.spin = (m.spin + m.w * dt) % (2f * Math.PI.toFloat())
        }
    }

    /**
     * Each slot's bounding sphere projected to a circle on screen (x, y, radius, 0), for the
     * shader's per-pixel cull: radius 0 for an empty slot or one behind the camera, and a
     * radius that covers the screen when the camera is inside or right at the sphere.
     */
    fun screen(out: FloatArray, travel: Double, pos: FloatArray, fw: FloatArray, basis: FloatArray, focal: Float = 1.3f) {
        for (i in 0 until SLOTS) {
            val m = marks[i]
            val o = i * 4
            out[o] = 0f; out[o + 1] = 0f; out[o + 2] = 0f; out[o + 3] = 0f
            if (m == null || m.x.isNaN()) continue
            val bx = m.x - pos[0]
            val by = m.y - pos[1]
            val bz = (m.z - travel).toFloat() - pos[2]
            val r = bound(m)
            val depth = bx * fw[0] + by * fw[1] + bz * fw[2]
            if (depth + r < 0f) continue
            if (depth - r < 0.15f) {
                out[o + 2] = 99f
                continue
            }
            out[o] = (bx * basis[0] + by * basis[1] + bz * basis[2]) * focal / depth
            out[o + 1] = (bx * basis[3] + by * basis[4] + bz * basis[5]) * focal / depth
            out[o + 2] = r * focal / (depth - r) + 0.02f
        }
    }

    /** The shader's bounding radius for each shape (JOURNEY_BODY). */
    private fun bound(m: Mark): Float = when (m.type) {
        0, CRYSTAL -> m.size + 0.05f
        2 -> m.size * 1.74f + 0.05f
        RING -> m.size + m.param + 0.05f
        TUNNEL -> kotlin.math.sqrt(m.w * m.w + (m.size + 2 * m.param + 1.5f).let { it * it })
        MONOLITH -> m.size * 2.3f + 0.05f
        SPHERE -> m.size + m.param + 0.05f
        else -> m.size * 1.7f + 0.4f
    }

    /** 8 vec4s for `uMarks`: two per slot, type -1 for an empty one. */
    fun pack(out: FloatArray, travel: Double) {
        for (i in 0 until SLOTS) {
            val m = marks[i]
            val o = i * 8
            if (m == null) {
                java.util.Arrays.fill(out, o, o + 8, 0f)
                out[o + 1] = -1f
                continue
            }
            out[o] = (m.z - travel).toFloat()
            out[o + 1] = m.type.toFloat()
            out[o + 2] = m.size
            out[o + 3] = if (m.type == TUNNEL) m.w else m.spin
            out[o + 4] = m.x
            out[o + 5] = m.y
            out[o + 6] = m.param
            out[o + 7] = m.hue
        }
    }

    private fun add(m: Mark): Boolean {
        val i = marks.indexOfFirst { it == null }
        if (i < 0) return false
        marks[i] = m
        return true
    }

    private fun large(allowed: IntArray, travel: Double, spawn: Double, speed: Float, clock: BeatClock?, nowMs: Long): Mark {
        val minMs = (spawn / speed * 1000.0).toFloat()
        val drop = clock?.msToDrop(nowMs, minMs, minMs + 20_000f)
        val ms = when {
            drop != null -> drop
            clock != null && clock.hasTempo -> clock.msToNextMultiple(nowMs, 16, minMs)
            else -> minMs + random.nextFloat() * 4_000f
        }
        val z = travel + speed * ms / 1000.0
        val hue = random.nextFloat()
        val spin = (random.nextFloat() - 0.5f) * 0.6f
        // A drop brings something to fly into, if the world has one; otherwise any of its own.
        val flyInto = allowed.filter { it == TUNNEL || it == SPHERE }
        val type = if (drop != null && flyInto.isNotEmpty()) flyInto[random.nextInt(flyInto.size)]
        else allowed[random.nextInt(allowed.size)]
        return when (type) {
            RING -> Mark(z, RING, 1.0f + random.nextFloat() * 1.2f, 0f, 0f, 0f, 0.06f + random.nextFloat() * 0.08f, hue)
            TUNNEL -> Mark(z, TUNNEL, 0.8f + random.nextFloat() * 0.4f, 2f + random.nextFloat() * 3f, 0f, 0f, 0.12f, hue)
            ARCH -> Mark(z, ARCH, 1.1f + random.nextFloat() * 0.7f, spin * 0.2f, 0f, 0f, 0f, hue)
            SPHERE -> Mark(z, SPHERE, 2.2f + random.nextFloat() * 1.0f, 0f, 0f, 0f, 0.12f, hue)
            else -> {
                // Off to one side, close enough to rush past.
                val side = if (random.nextBoolean()) 1f else -1f
                val size = if (type == MONOLITH) 0.8f + random.nextFloat() * 0.8f else 0.6f + random.nextFloat() * 0.6f
                Mark(z, type, size, spin, side * (1.4f + random.nextFloat() * 1.6f), (random.nextFloat() - 0.5f) * 1.5f, 0f, hue)
            }
        }
    }

    companion object {
        /** Big structures come one at a time with gaps between, so four is plenty. */
        const val SLOTS = 4
        const val CRYSTAL = 1
        const val RING = 3
        const val TUNNEL = 4
        const val MONOLITH = 5
        const val SPHERE = 6
        const val ARCH = 7
        /** Just past the fog: 5 units in the enclosed worlds, 18 in the open sky. */
        const val TUBE_SPAWN = 6.0
        const val OPEN_SPAWN = 17.0
    }
}

/**
 * The Journey's camera, worked out on the CPU in full precision so it is steady on GPUs with
 * only 16-bit floats: its position is the path's at the camera, and its heading eases toward
 * the average of three points 2 to 4.5 units ahead, so the path's small wiggles and a
 * swerve's first jolt are smoothed into a glide. [basis] folds the roll in.
 */
class JourneyCamera {
    /** Position: the path at the camera (x, y); the camera is always at z = 0. */
    val pos = FloatArray(3)
    /** Heading, a unit vector. */
    val fw = floatArrayOf(0f, 0f, 1f)
    private var started = false

    fun update(dt: Float, camZ: Double, path: JourneyPath) {
        val px = path.xAt(camZ)
        val py = JourneyPath.baseY(camZ).toFloat()
        pos[0] = px
        pos[1] = py
        pos[2] = 0f
        var tx = 0f
        var ty = 0f
        var tz = 0f
        for (d in LOOK) {
            tx += path.xAt(camZ + d) - px
            ty += JourneyPath.baseY(camZ + d).toFloat() - py
            tz += d.toFloat()
        }
        val l = kotlin.math.sqrt(tx * tx + ty * ty + tz * tz)
        tx /= l; ty /= l; tz /= l
        val k = if (started) 1f - kotlin.math.exp(-dt * HEADING_RATE) else 1f
        started = true
        fw[0] += (tx - fw[0]) * k
        fw[1] += (ty - fw[1]) * k
        fw[2] += (tz - fw[2]) * k
        val n = kotlin.math.sqrt(fw[0] * fw[0] + fw[1] * fw[1] + fw[2] * fw[2])
        fw[0] /= n; fw[1] /= n; fw[2] /= n
    }

    /** Right and up for a [roll] in radians, into [out] (rx, ry, rz, ux, uy, uz). */
    fun basis(roll: Float, out: FloatArray) {
        // right = Y × fw, up = fw × right.
        var rx = fw[2]
        var rz = -fw[0]
        val rl = kotlin.math.sqrt(rx * rx + rz * rz).coerceAtLeast(1e-4f)
        rx /= rl; rz /= rl
        val ux = fw[1] * rz
        val uy = fw[2] * rx - fw[0] * rz
        val uz = -fw[1] * rx
        val c = kotlin.math.cos(roll)
        val s = kotlin.math.sin(roll)
        out[0] = c * rx + s * ux; out[1] = s * uy; out[2] = c * rz + s * uz
        out[3] = -s * rx + c * ux; out[4] = c * uy; out[5] = -s * rz + c * uz
    }

    private companion object {
        // Further ahead and eased more gently than at first: the heading glides through turns.
        val LOOK = doubleArrayOf(2.0, 3.2, 4.5)
        const val HEADING_RATE = 1.6f
    }
}

/**
 * What each Journey world asks of the CPU side: which big landmarks suit it (none for the
 * enclosed lattices), how far ahead they appear (just past its fog), how fast it flies, whether
 * the camera only banks (worlds with a floor) or rolls right round, and its cell along z for
 * `uCam.w` / `uCell` (matching JCELL / JCELLS in JOURNEY_BODY).
 */
data class JourneyWorld(
    val large: IntArray,
    val spawn: Double,
    val speed: Float,
    val bankOnly: Boolean,
    val cell: Double,
    val cells: Double,
    /** Whether schools of fish (or birds) fly in it (JourneyFlock). */
    val flock: Boolean = false,
    /** Its fog distance, JFAR in JOURNEY_BODY (the fish fade out by it). */
    val far: Float = 17f,
    /** Its flock is jellyfish rather than fish. */
    val jelly: Boolean = false,
) {
    companion object {
        private val SHEET = 2.0 * Math.PI / 3.0
        private val ENCLOSED = JourneyWorld(IntArray(0), JourneyLandmarks.TUBE_SPAWN, 1f, false, SHEET, 9.0)

        // Built once: the renderer asks every frame, and JourneyLandmarks tells worlds apart by identity.
        private val worlds = HashMap<DemoEffect, JourneyWorld>()

        fun of(e: DemoEffect): JourneyWorld = worlds.getOrPut(e) { build(e) }

        private fun build(e: DemoEffect): JourneyWorld = with(JourneyLandmarks) {
            when (e) {
                // Bubbles and pillars stand close together, so the same speed felt too fast there.
                DemoEffect.BUBBLEFLIGHT -> ENCLOSED.copy(speed = 0.6f, cell = 6.0 * Math.PI / 20.0, cells = 20.0)
                // The temples are best taken slowly: there is a lot to see in every hall.
                DemoEffect.TEMPLE, DemoEffect.TWISTTEMPLE, DemoEffect.LATTICE -> ENCLOSED.copy(speed = 0.45f)
                DemoEffect.PILLARS -> ENCLOSED.copy(speed = 0.6f, bankOnly = true, cell = 6.0 * Math.PI / 12.0, cells = 12.0)
                DemoEffect.CANYON -> JourneyWorld(intArrayOf(ARCH, ARCH, RING, TUNNEL, TUNNEL, MONOLITH), 13.0, 1.3f, true, SHEET, 9.0, far = 14f)
                DemoEffect.SEASTACKS -> JourneyWorld(intArrayOf(RING, ARCH, SPHERE, TUNNEL, TUNNEL), 16.0, 1.4f, true, Math.PI, 6.0, flock = true)
                DemoEffect.NIGHTCITY -> JourneyWorld(intArrayOf(RING, TUNNEL, TUNNEL, ARCH), 13.0, 1.2f, true, 6.0 * Math.PI / 8.0, 8.0, far = 14f)
                DemoEffect.STATION -> JourneyWorld(intArrayOf(RING, TUNNEL, TUNNEL, SPHERE), 13.0, 1.3f, false, 6.0 * Math.PI / 8.0, 8.0, far = 14f)
                DemoEffect.ASTEROIDS -> JourneyWorld(intArrayOf(SPHERE, RING, TUNNEL, TUNNEL), 13.0, 1.2f, false, 6.0 * Math.PI / 7.0, 7.0, far = 14f)
                DemoEffect.CAVES -> JourneyWorld(intArrayOf(RING, TUNNEL), 7.5, 1.0f, false, 6.0 * Math.PI / 5.0, 5.0, far = 8f)
                DemoEffect.ABYSS -> JourneyWorld(intArrayOf(ARCH, ARCH, TUNNEL, TUNNEL, SPHERE), 10.5, 1.0f, true, 6.0 * Math.PI / 12.0, 12.0, flock = true, far = 11f)
                DemoEffect.LAVA -> JourneyWorld(intArrayOf(ARCH, ARCH, TUNNEL, RING, MONOLITH), 13.0, 1.2f, true, SHEET, 9.0, far = 14f)
                DemoEffect.REEF -> JourneyWorld(intArrayOf(ARCH, RING, TUNNEL, SPHERE), 11.5, 1.0f, true, SHEET, 9.0, flock = true, far = 12f)
                DemoEffect.CYBER -> JourneyWorld(intArrayOf(RING, RING, TUNNEL, TUNNEL, SPHERE), 13.0, 1.5f, false, SHEET, 9.0, far = 14f)
                DemoEffect.TUNDRA -> JourneyWorld(intArrayOf(ARCH, RING, TUNNEL, MONOLITH), 13.0, 1.3f, true, SHEET, 9.0, far = 14f)
                DemoEffect.DEEP -> JourneyWorld(intArrayOf(RING, TUNNEL, SPHERE), 11.0, 0.9f, true, SHEET, 9.0, flock = true, far = 12f, jelly = true)
                DemoEffect.SYNTHWAVEROAD -> JourneyWorld(intArrayOf(ARCH, ARCH, ARCH, RING, TUNNEL), 16.0, 1.6f, true, SHEET, 9.0)
                DemoEffect.TESSERACT -> JourneyWorld(intArrayOf(RING, TUNNEL, SPHERE), 13.0, 0.55f, true, SHEET, 9.0, far = 14f)
                else -> ENCLOSED
            }
        }
    }
}

/**
 * The viewer's Journey options from the TV's Visualizer settings, stored as one string
 * ([encode]/[decode]) so an unknown or partial value falls back field by field.
 *
 * - [length]: time in each world, 0 short (16-beat phrases, from 10 s), 1 normal (32 beats,
 *   from 20 s), 2 long (64 beats, from 40 s).
 * - [speed]: 0 calm, 1 normal, 2 fast.
 * - [rings], [fish]: the rings to fly through and the fish and jellyfish.
 * - [shuffle]: each track flies the worlds in its own order; off, always the same order.
 * - [ringPattern]: 0 a mix, or always one: 1 straight, 2 corkscrew, 3 narrowing, 4 long runs,
 *   5 sweeping curve (JourneyHoops).
 * - [style]: 0 a mix (a new pick at every world, mostly as made), or always one: 1 as made,
 *   2 duotone, 3 night (jStyle).
 * - [camera]: the director's other shots and lens changes (JourneyDirector).
 * - [drops]: the drop moments (flash, inverted beat, shockwave).
 * - [weather]: time of day and weather over the open worlds.
 * - [boards]: the album cover and track title on billboards (JourneyBoard).
 * - [mirror]: mirror bars, the picture folded in two or four for 8 beats.
 * - [kickFx]: colour split and a zoom punch on each kick.
 * - [interludes]: now and then a scene (a planet, the galaxy...) for a phrase between worlds.
 */
data class JourneyOptions(
    val length: Int = 1,
    val speed: Int = 1,
    val rings: Boolean = true,
    val fish: Boolean = true,
    val shuffle: Boolean = true,
    val ringPattern: Int = 0,
    val style: Int = 0,
    val camera: Boolean = true,
    val drops: Boolean = true,
    val weather: Boolean = true,
    val boards: Boolean = true,
    val mirror: Boolean = true,
    val kickFx: Boolean = false,
    val interludes: Boolean = true,
    /** Moments (every effect, not only the Journey): 0 off, 1 subtle, 2 mixed, 3 striking. */
    val moments: Int = 2,
    /** How often moments come: 0 rare, 1 normal, 2 often. */
    val momentRate: Int = 1,
    /** Moments may glimpse or ghost another world in. */
    val glimpses: Boolean = true,
) {
    /** Time of day for the next world (JourneyLook.sky): mostly as made. */
    fun pickSky(random: kotlin.random.Random): Int =
        if (!weather) 0 else random.nextFloat().let { if (it < 0.45f) 0 else 1 + random.nextInt(3) }

    /** Weather for the next world (JourneyLook.weather), before JourneyDirector.weatherIn. */
    fun pickWeather(random: kotlin.random.Random): Int =
        if (!weather) 0 else random.nextFloat().let { if (it < 0.45f) 0 else if (it < 0.65f) 1 else if (it < 0.8f) 2 else 3 }

    /** A style for the next world (JourneyLook.style): the chosen one, or a weighted pick. */
    fun pickStyle(random: kotlin.random.Random): Int = when (style) {
        1 -> 0
        2 -> 1
        3 -> 2
        else -> random.nextFloat().let { if (it < 0.6f) 0 else if (it < 0.8f) 1 else 2 }
    }

    /** How much longer than normal each world lasts. */
    val lengthScale: Float get() = when (length) { 0 -> 0.5f; 2 -> 2f; else -> 1f }
    /** The flight speed against normal. */
    val speedScale: Float get() = when (speed) { 0 -> 0.65f; 2 -> 1.4f; else -> 1f }

    fun encode(): String =
        listOf(
            length, speed, b(rings), b(fish), b(shuffle), ringPattern, style,
            b(camera), b(drops), b(weather), b(boards), b(mirror), b(kickFx), b(interludes), moments, momentRate, b(glimpses),
        ).joinToString(",")

    private fun b(v: Boolean) = if (v) 1 else 0

    companion object {
        val LENGTH_LABELS = listOf("Short", "Normal", "Long")
        val SPEED_LABELS = listOf("Calm", "Normal", "Fast")
        val STYLE_LABELS = listOf("Mixed", "As made", "Duotone", "Night")
        val RING_LABELS = listOf("Mixed", "Straight", "Corkscrew", "Narrowing", "Long runs", "Sweeping curve")

        fun decode(raw: String?): JourneyOptions {
            val p = raw?.split(",")?.map { it.trim().toIntOrNull() } ?: emptyList()
            val d = JourneyOptions()
            return JourneyOptions(
                length = p.getOrNull(0)?.takeIf { it in 0..2 } ?: d.length,
                speed = p.getOrNull(1)?.takeIf { it in 0..2 } ?: d.speed,
                rings = p.getOrNull(2)?.let { it != 0 } ?: d.rings,
                fish = p.getOrNull(3)?.let { it != 0 } ?: d.fish,
                shuffle = p.getOrNull(4)?.let { it != 0 } ?: d.shuffle,
                ringPattern = p.getOrNull(5)?.takeIf { it in 0..5 } ?: d.ringPattern,
                style = p.getOrNull(6)?.takeIf { it in 0..3 } ?: d.style,
                camera = p.getOrNull(7)?.let { it != 0 } ?: d.camera,
                drops = p.getOrNull(8)?.let { it != 0 } ?: d.drops,
                weather = p.getOrNull(9)?.let { it != 0 } ?: d.weather,
                boards = p.getOrNull(10)?.let { it != 0 } ?: d.boards,
                mirror = p.getOrNull(11)?.let { it != 0 } ?: d.mirror,
                kickFx = p.getOrNull(12)?.let { it != 0 } ?: d.kickFx,
                interludes = p.getOrNull(13)?.let { it != 0 } ?: d.interludes,
                moments = p.getOrNull(14)?.takeIf { it in 0..3 } ?: d.moments,
                momentRate = p.getOrNull(15)?.takeIf { it in 0..2 } ?: d.momentRate,
                glimpses = p.getOrNull(16)?.let { it != 0 } ?: d.glimpses,
            )
        }
    }
}

/**
 * The Journey camera's roll over and above its gentle sway: now and then (every 8 to 25
 * seconds, on a bar when the tempo is known) it rolls, usually a slow quarter or half turn
 * and back, sometimes a full turn, and now and then a quick barrel roll, each eased in and out
 * so it starts and settles smoothly and always comes back level.
 */
class JourneyRoll(seed: Int = 31) {
    private val random = kotlin.random.Random(seed)
    private var wait = 6f
    private var t = 0f
    private var length = 0f
    private var amount = 0f
    private var back = false

    /** The roll to add now, in radians. */
    var value = 0f
        private set

    /** For tests: whether a roll is under way. */
    val rolling: Boolean get() = length > 0f

    fun update(dt: Float, clock: BeatClock?, nowMs: Long) {
        if (length <= 0f) {
            value = 0f
            wait -= dt
            if (wait > 0f) return
            // On a bar when the tempo is known: hold off until the next one is close.
            if (clock != null && clock.hasTempo && clock.msToNextMultiple(nowMs, clock.beatsPerBar) > 120f) return
            val r = random.nextFloat()
            val dir = if (random.nextBoolean()) 1f else -1f
            when {
                r < 0.45f -> { amount = dir * (Math.PI / 2).toFloat(); length = 5f + random.nextFloat() * 3f; back = true }
                r < 0.7f -> { amount = dir * Math.PI.toFloat(); length = 6f + random.nextFloat() * 3f; back = true }
                r < 0.88f -> { amount = dir * (2 * Math.PI).toFloat(); length = 7f + random.nextFloat() * 4f; back = false }
                else -> { amount = dir * (2 * Math.PI).toFloat(); length = 1.6f + random.nextFloat() * 0.8f; back = false }
            }
            t = 0f
        }
        t += dt
        val f = (t / length).coerceIn(0f, 1f)
        // Out and back for a part turn; a full turn just goes round and ends level.
        val shape = if (back) kotlin.math.sin(Math.PI.toFloat() * f) else f
        val eased = if (back) shape * shape * (3f - 2f * shape) else shape * shape * (3f - 2f * shape)
        value = amount * eased
        if (f >= 1f) {
            length = 0f
            value = 0f
            wait = 8f + random.nextFloat() * 17f
        }
    }
}
