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
                BeatGrid(r.bpm, r.downbeatS * 1000f, r.beatsPerBar ?: 4, r.drops)
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
