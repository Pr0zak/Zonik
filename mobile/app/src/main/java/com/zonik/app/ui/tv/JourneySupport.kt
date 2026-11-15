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
