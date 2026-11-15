package com.zonik.app.ui.tv

/**
 * Rings to fly through, in every Journey world: runs of three or four glowing rings round the
 * path, each placed where the camera will be on a beat, so it passes through them in time with
 * the music. A run starts on the next 8-beat boundary past the fog, and the next run waits for
 * the next 16-beat one after the last ring of this one. Without a tempo the rings come at
 * random gaps of a few seconds.
 *
 * The shader draws them in closed form (`jHoops` in JOURNEY_BODY: where the ray crosses each
 * ring's plane), not in a ray march, so they cost the slow TVs almost nothing. Pure logic, no
 * GL, no allocation per frame; positions along the flight ([travel]) like the landmarks.
 */
class JourneyHoops(seed: Int = 23) {
    private val random = kotlin.random.Random(seed)
    private val z = DoubleArray(SLOTS) { Double.NaN }
    private val x = FloatArray(SLOTS) { Float.NaN }
    private val y = FloatArray(SLOTS)
    private val radius = FloatArray(SLOTS)
    private val width = FloatArray(SLOTS)
    private val hue = FloatArray(SLOTS)
    private var nextRunZ = Double.NaN
    private var lastWorld: JourneyWorld? = null

    /** For tests: the rings in use, as distances ahead of [travel], nearest first. */
    fun ahead(travel: Double): List<Double> = z.filter { !it.isNaN() }.map { it - travel }.sorted()

    fun radiusOf(i: Int): Float = radius[i]

    fun update(
        world: JourneyWorld, travel: Double, camZ: Double, unitsPerSec: Float,
        clock: BeatClock?, nowMs: Long, dt: Float, path: JourneyPath,
    ) {
        for (i in 0 until SLOTS) if (!z[i].isNaN() && z[i] < travel - 0.5) z[i] = Double.NaN
        if (world !== lastWorld) {
            lastWorld = world
            nextRunZ = Double.NaN
            // A ring sized for the last world may not fit this one: drop those not yet near.
            for (i in 0 until SLOTS) if (!z[i].isNaN() && z[i] > travel + 3.0) z[i] = Double.NaN
        }
        val spawn = world.spawn
        val speed = unitsPerSec.coerceAtLeast(0.3f)
        if (nextRunZ.isNaN()) nextRunZ = travel + spawn
        if (travel + spawn >= nextRunZ && z.all { it.isNaN() }) placeRun(world, travel, spawn, speed, clock, nowMs)
        for (i in 0 until SLOTS) {
            if (z[i].isNaN()) continue
            val along = camZ + (z[i] - travel)
            val tx = path.xAt(along)
            val ty = JourneyPath.baseY(along).toFloat()
            if (x[i].isNaN()) {
                x[i] = tx
                y[i] = ty
            } else {
                // Eased onto the path, so a turn placed after them drifts them across.
                val k = 1f - kotlin.math.exp(-dt * 1.5f)
                x[i] += (tx - x[i]) * k
                y[i] += (ty - y[i]) * k
            }
        }
    }

    private fun placeRun(world: JourneyWorld, travel: Double, spawn: Double, speed: Float, clock: BeatClock?, nowMs: Long) {
        val enclosed = world.large.isEmpty()
        val count = 3 + random.nextInt(2)
        val minMs = (spawn / speed * 1000.0).toFloat()
        val beat = clock?.takeIf { it.hasTempo }
        // On beats when the tempo is known: every beat, or every other one when beats come so
        // fast the rings would crowd together.
        val stepMs = if (beat != null) beat.beatMs * (if (beat.beatMs * speed / 1000f < 0.45f) 2 else 1) else 700f
        val startMs = beat?.msToNextMultiple(nowMs, 8, minMs) ?: minMs
        val h = random.nextFloat()
        val r = if (enclosed) 0.3f else 0.55f + random.nextFloat() * 0.35f
        var lastZ = travel
        for (k in 0 until count) {
            val zk = travel + speed * (startMs + k * stepMs) / 1000.0
            z[k] = zk
            x[k] = Float.NaN
            radius[k] = r
            width[k] = if (enclosed) 0.022f else 0.045f
            hue[k] = h + k * 0.06f
            lastZ = zk
        }
        // The next run: past this one and at least a few seconds on.
        val gapMs = beat?.let { (it.beatMs * 16f).coerceAtLeast(4_000f) } ?: (5_000f + random.nextFloat() * 5_000f)
        nextRunZ = lastZ + speed * gapMs / 1000.0
    }

    /** 8 vec4s for `uHoops`: (z ahead, centre x, centre y, radius; width, hue, 0, 0), radius 0 for none. */
    fun pack(out: FloatArray, travel: Double) {
        for (i in 0 until SLOTS) {
            val o = i * 8
            java.util.Arrays.fill(out, o, o + 8, 0f)
            if (z[i].isNaN() || x[i].isNaN()) continue
            out[o] = (z[i] - travel).toFloat()
            out[o + 1] = x[i]
            out[o + 2] = y[i]
            out[o + 3] = radius[i]
            out[o + 4] = width[i]
            out[o + 5] = hue[i]
        }
    }

    companion object {
        const val SLOTS = 4
    }
}
