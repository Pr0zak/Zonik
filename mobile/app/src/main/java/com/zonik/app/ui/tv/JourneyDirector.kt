package com.zonik.app.ui.tv

import kotlin.math.exp
import kotlin.math.sqrt

/**
 * The Journey's director: films the flight with more than one camera. Most of the time it is
 * the chase camera on the path; now and then, on an 8-beat boundary (every few seconds without
 * a tempo), it cuts to another shot for 8 beats and back:
 *
 * - [BACK]: the same place, looking back down the path at the world going away.
 * - [CRANE]: rising up and away above the path, looking down at the flight ahead (open
 *   worlds with a floor).
 * - [SIDE]: drifting out to one side on a longer lens, looking back in at the path (open
 *   worlds).
 *
 * The enclosed worlds' tube has no room off the path, so they only ever look back. The camera
 * always stays at z = 0, where the shaders and the closed-form rings expect it.
 *
 * It also times the other moments over a world: a drop (the beat grid's, or a big bass entry
 * after a quiet stretch without one) flashes, inverts for a beat and sends a shockwave out, and
 * cuts to the crane where there is room; mirror bars fold the picture into two or four for 8
 * beats; and the lens widens with the energy.
 *
 * Pure logic, no GL; positions in the same frame as [JourneyCamera].
 */
class JourneyDirector(seed: Int = 41) {
    private val random = kotlin.random.Random(seed)

    var shot = CHASE
        private set
    /** 0..1 through the current shot. */
    var progress = 0f
        private set
    private var shotSec = 0f
    private var shotLen = 0f
    private var chaseSec = 0f
    private var side = 1f
    private var lastBlock = Long.MIN_VALUE

    /** Multiplies the focal length: below 1 wider, above 1 a longer lens. */
    var lens = 1f
        private set

    /** 0 none, 1 mirrored left to right, 2 into four. */
    var mirror = 0
        private set
    private var mirrorSec = 0f

    /** Seconds since the last drop moment (large when there has been none). */
    var dropAge = 99f
        private set
    private var lastDropBar = Int.MIN_VALUE
    private var quietSec = 0f
    private var beatSec = 0.5f

    /** The drop moment's flash, 0..1. */
    val flash: Float get() = if (dropAge < 1.5f) exp(-dropAge * 5f) else 0f
    /** The shockwave's way out, 0..1, or 1 when there is none. */
    val shock: Float get() = (dropAge / 1.2f).coerceAtMost(1f)
    /** The inverted picture for the beat after a drop, 0..1. */
    val invert: Float get() = when {
        dropAge < beatSec * 0.85f -> 1f
        dropAge < beatSec -> (beatSec - dropAge) / (beatSec * 0.15f)
        else -> 0f
    }

    /**
     * [room]: the world has space off the path (an open world); [crane]: it has a floor and
     * sky to rise into. [busy]: a portal is coming or under way, so only the chase camera.
     */
    fun update(
        dt: Float, clock: BeatClock?, nowMs: Long, room: Boolean, crane: Boolean,
        shots: Boolean, drops: Boolean, mirrors: Boolean, busy: Boolean,
        low: Float, kick: Float, energy: Float,
    ) {
        val tempo = clock?.takeIf { it.hasTempo }
        if (tempo != null) beatSec = tempo.beatMs / 1000f
        dropAge += dt
        if (drops && detectDrop(dt, tempo, nowMs, low, kick)) {
            dropAge = 0f
            if (shots && !busy && room && crane) cut(CRANE, tempo)
        }

        // Shot changes on 8-beat blocks, or every few seconds without a tempo.
        val block = tempo?.let { kotlin.math.floor(it.beatAt(nowMs) / 8.0).toLong() }
        val newBlock = block != null && block != lastBlock
        if (block != null) lastBlock = block
        shotSec += dt
        if (shot != CHASE) {
            progress = (shotSec / shotLen).coerceIn(0f, 1f)
            if (busy || !shots || shotSec >= shotLen || (shot != BACK && !room) || (shot == CRANE && !crane)) toChase()
        } else {
            chaseSec += dt
            progress = 0f
            val due = if (tempo != null) newBlock && chaseSec > 5f else chaseSec > 9f
            if (shots && !busy && due && random.nextFloat() < (if (tempo != null) 0.4f else 0.5f)) {
                val choices = when {
                    room && crane -> intArrayOf(BACK, CRANE, SIDE, SIDE)
                    room -> intArrayOf(BACK, SIDE)
                    else -> intArrayOf(BACK)
                }
                cut(choices[random.nextInt(choices.size)], tempo)
            } else if (due && tempo == null) {
                chaseSec = 0f
            }
        }

        // Mirror bars: on a block while chasing, for one block.
        mirrorSec -= dt
        if (mirror != 0 && (mirrorSec <= 0f || !mirrors || busy)) mirror = 0
        val mirrorDue = if (tempo != null) newBlock else random.nextFloat() < dt / 30f
        if (mirrors && !busy && mirror == 0 && shot == CHASE && mirrorDue && random.nextFloat() < 0.15f) {
            mirror = if (random.nextFloat() < 0.6f) 1 else 2
            mirrorSec = tempo?.let { it.beatMs * 8f / 1000f } ?: 4f
        }

        // The lens: wide when the music is loud, long for the side shot.
        val target = when (shot) {
            SIDE -> 1.55f
            BACK -> 1.1f
            CRANE -> 0.95f
            else -> if (shots) 1.05f - 0.2f * energy.coerceIn(0f, 1f) else 1f
        }
        lens += (target - lens) * (1f - exp(-dt * 1.5f))
    }

    private fun cut(to: Int, tempo: BeatClock?) {
        shot = to
        shotSec = 0f
        progress = 0f
        shotLen = tempo?.let { it.beatMs * 8f / 1000f }?.coerceIn(3f, 8f) ?: 4.5f
        side = if (random.nextBoolean()) 1f else -1f
        // A cut is a cut: the lens jumps with it.
        lens = when (to) { SIDE -> 1.55f; BACK -> 1.1f; CRANE -> 0.95f; else -> lens }
    }

    private fun toChase() {
        if (shot != CHASE) {
            shot = CHASE
            lens = 1f
        }
        shotSec = 0f
        chaseSec = 0f
        progress = 0f
    }

    /** The beat grid's drop when there is one; otherwise a big bass entry after a quiet stretch. */
    private fun detectDrop(dt: Float, tempo: BeatClock?, nowMs: Long, low: Float, kick: Float): Boolean {
        val grid = tempo?.grid
        if (tempo != null && grid != null && tempo.synced && grid.drops.isNotEmpty()) {
            if (tempo.msToDrop(nowMs, -250f, 0f) != null) {
                val bar = kotlin.math.round(tempo.beatAt(nowMs) / grid.beatsPerBar).toInt()
                if (bar != lastDropBar) {
                    lastDropBar = bar
                    return true
                }
            }
            return false
        }
        if (low < 0.3f) quietSec += dt else if (low > 0.5f) quietSec = (quietSec - dt * 4f).coerceAtLeast(0f)
        if (quietSec > 6f && low > 0.6f && kick > 0.8f && dropAge > 30f) {
            quietSec = 0f
            return true
        }
        return false
    }

    /** The shot's camera from the chase camera [cam], into [out]. */
    fun apply(cam: JourneyCamera, out: JourneyCamera, path: JourneyPath, camZ: Double) {
        for (i in 0..2) { out.pos[i] = cam.pos[i]; out.fw[i] = cam.fw[i] }
        val e = progress * progress * (3f - 2f * progress)
        when (shot) {
            BACK -> for (i in 0..2) out.fw[i] = -cam.fw[i]
            CRANE -> {
                out.pos[1] += 0.25f + 2.1f * e
                lookAt(out, path, camZ, 4.0 + 2.0 * e)
            }
            SIDE -> {
                // Out along the heading's right, a little up.
                var rx = cam.fw[2]
                var rz = -cam.fw[0]
                val rl = sqrt(rx * rx + rz * rz).coerceAtLeast(1e-4f)
                rx /= rl; rz /= rl
                val o = side * (0.3f + 0.35f * e)
                out.pos[0] += rx * o
                out.pos[1] += 0.2f + 0.15f * e
                // Only sideways: z stays 0.
                out.pos[2] = 0f
                lookAt(out, path, camZ, 3.5)
            }
        }
    }

    private fun lookAt(out: JourneyCamera, path: JourneyPath, camZ: Double, ahead: Double) {
        val tx = path.xAt(camZ + ahead) - out.pos[0]
        val ty = JourneyPath.baseY(camZ + ahead).toFloat() - out.pos[1]
        val tz = ahead.toFloat() - out.pos[2]
        val l = sqrt(tx * tx + ty * ty + tz * tz)
        out.fw[0] = tx / l; out.fw[1] = ty / l; out.fw[2] = tz / l
    }

    companion object {
        const val CHASE = 0
        const val BACK = 1
        const val CRANE = 2
        const val SIDE = 3

        const val WEATHER_NONE = 0
        const val RAIN = 1
        const val SNOW = 2
        const val FOG = 3

        /** Whether [e] has room off its path for the side shot (an open world, not the caves). */
        fun roomIn(e: DemoEffect): Boolean = JourneyWorld.of(e).large.isNotEmpty() && e != DemoEffect.CAVES

        /** Whether [e] has a floor and open sky above it for the crane. */
        fun craneIn(e: DemoEffect): Boolean = roomIn(e) && JourneyWorld.of(e).bankOnly && e != DemoEffect.ABYSS

        /**
         * The weather [wanted] for a world, or none where it would make no sense: under water,
         * in space, in the lava canyon (it has its embers), or the enclosed worlds.
         */
        fun weatherIn(e: DemoEffect, wanted: Int): Int = when (e) {
            DemoEffect.ABYSS, DemoEffect.REEF, DemoEffect.DEEP, DemoEffect.STATION, DemoEffect.ASTEROIDS,
            DemoEffect.LAVA, DemoEffect.CAVES, DemoEffect.PINBALL, DemoEffect.SPEAKERCANYON -> WEATHER_NONE
            DemoEffect.TUNDRA -> if (wanted == RAIN) SNOW else wanted
            DemoEffect.CYBER, DemoEffect.SYNTHWAVEROAD, DemoEffect.NIGHTCITY -> if (wanted == SNOW) RAIN else wanted
            else -> if (roomIn(e)) wanted else WEATHER_NONE
        }
    }
}

/**
 * Billboards in the open worlds: the album cover, or the track's title when a new track has
 * just started, on a giant panel standing beside the path ahead, so the camera flies past it.
 * One at a time, every half a minute or so; drawn in closed form like the rings (`jBoard`).
 */
class JourneyBoard(seed: Int = 53) {
    private val random = kotlin.random.Random(seed)
    private var z = Double.NaN
    private var offX = 0f
    private var offY = 0f
    private var size = 1f
    var kind = COVER
        private set
    private var wait = 6f
    private var titleDue = false
    private var lastTitle = ""

    /** For tests: the board's distance ahead of [travel], or null with none up. */
    fun ahead(travel: Double): Double? = if (z.isNaN()) null else z - travel

    fun update(dt: Float, travel: Double, spawn: Double, room: Boolean, on: Boolean, title: String) {
        if (title.isNotBlank() && title != lastTitle) {
            lastTitle = title
            titleDue = true
            wait = minOf(wait, 2f)
        }
        if (!z.isNaN() && (z < travel - 1.0 || !on || !room)) z = Double.NaN
        if (!on || !room || !z.isNaN()) return
        wait -= dt
        if (wait > 0f) return
        kind = if (titleDue) TITLE else COVER
        titleDue = false
        z = travel + spawn * 0.85
        val s = if (random.nextBoolean()) 1f else -1f
        offX = s * (1.5f + random.nextFloat() * 0.6f)
        offY = 0.55f + random.nextFloat() * 0.5f
        size = if (kind == TITLE) 1.5f else 0.85f + random.nextFloat() * 0.25f
        wait = 22f + random.nextFloat() * 20f
    }

    /** `uBoard` (z ahead, centre x, centre y, half width) and `uBoard2` (kind, 0, 0, 0) into [out]. */
    fun pack(out: FloatArray, travel: Double, camZ: Double, path: JourneyPath) {
        java.util.Arrays.fill(out, 0f)
        if (z.isNaN()) return
        val ahead = z - travel
        if (ahead < 0.05) return
        out[0] = ahead.toFloat()
        out[1] = path.xAt(camZ + ahead) + offX
        out[2] = JourneyPath.baseY(camZ + ahead).toFloat() + offY
        out[3] = size
        out[4] = kind.toFloat()
    }

    companion object {
        const val COVER = 0
        const val TITLE = 1
    }
}
