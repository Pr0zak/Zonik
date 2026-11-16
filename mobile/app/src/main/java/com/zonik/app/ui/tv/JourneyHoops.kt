package com.zonik.app.ui.tv

/**
 * Rings to fly through, in every Journey world: runs of three to six glowing rings round the
 * path, each placed where the camera will be on a beat, so it passes through them in time with
 * the music. A run starts on the next 8-beat boundary past the fog, and the next run waits for
 * the next 16-beat one after the last ring of this one. Without a tempo the rings come at
 * random gaps of a few seconds.
 *
 * Each run takes a pattern (a mix, or the one the viewer picked): straight down the path; a
 * corkscrew of big rings winding round it; narrowing, each ring smaller than the last; a long
 * run of six on every beat; or a sweep out to one side and back as if round a bend. The tunnel
 * worlds' tube has no room for the corkscrew or the sweep, so those narrow there instead.
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
    private val offX = FloatArray(SLOTS)
    private val offY = FloatArray(SLOTS)
    /** The last run's pattern (STRAIGHT..CURVE). */
    var pattern = STRAIGHT
        private set
    /** The viewer's choice (JourneyOptions.ringPattern): 0 a mix, or one of STRAIGHT..CURVE. */
    var forced = 0
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
        // The viewer's choice, or a mix; the tunnel worlds' tube has no room to corkscrew or
        // sweep, so those narrow instead.
        pattern = if (forced in STRAIGHT..CURVE) forced else STRAIGHT + random.nextInt(5)
        if (enclosed && (pattern == CORKSCREW || pattern == CURVE)) pattern = NARROWING
        val count = when (pattern) {
            LONG -> SLOTS
            CORKSCREW, NARROWING, CURVE -> 5
            else -> 3 + random.nextInt(2)
        }
        val minMs = (spawn / speed * 1000.0).toFloat()
        val beat = clock?.takeIf { it.hasTempo }
        // On beats when the tempo is known: every beat, or every other one when beats come so
        // fast the rings would crowd together (long runs keep every beat).
        val stepMs = if (beat != null) beat.beatMs * (if (pattern != LONG && beat.beatMs * speed / 1000f < 0.45f) 2 else 1) else 700f
        val startMs = beat?.msToNextMultiple(nowMs, 8, minMs) ?: minMs
        val h = random.nextFloat()
        val r = if (enclosed) 0.3f else 0.6f + random.nextFloat() * 0.3f
        val turn = if (random.nextBoolean()) 1f else -1f
        var lastZ = travel
        for (k in 0 until count) {
            val zk = travel + speed * (startMs + k * stepMs) / 1000.0
            val f = k / (count - 1f).coerceAtLeast(1f)
            z[k] = zk
            x[k] = Float.NaN
            width[k] = if (enclosed) 0.022f else 0.05f
            hue[k] = h + k * 0.07f
            offX[k] = 0f
            offY[k] = 0f
            radius[k] = r
            when (pattern) {
                CORKSCREW -> {
                    // Big rings whose centres wind round the path, a third of a turn each:
                    // the camera, on the path, still passes through every one.
                    val a = turn * k * 2.1f + h * 6.28f
                    radius[k] = 0.95f
                    offX[k] = 0.5f * kotlin.math.cos(a)
                    offY[k] = 0.42f * kotlin.math.sin(a)
                }
                // Each ring smaller than the last, down to a squeeze.
                NARROWING -> radius[k] = (if (enclosed) 0.39f - 0.19f * f else 1.5f - 1.0f * f)
                CURVE -> {
                    // A run that sweeps out to one side and back, as if round a bend.
                    radius[k] = 0.95f
                    offX[k] = turn * 0.55f * kotlin.math.sin(f * Math.PI.toFloat())
                    offY[k] = 0.3f * kotlin.math.sin(f * Math.PI.toFloat() * 2f)
                }
            }
            lastZ = zk
        }
        // The next run: past this one and at least a few seconds on.
        val gapMs = beat?.let { (it.beatMs * 16f).coerceAtLeast(4_000f) } ?: (5_000f + random.nextFloat() * 5_000f)
        nextRunZ = lastZ + speed * gapMs / 1000.0
    }

    /** 12 vec4s for `uHoops`: (z ahead, centre x, centre y, radius; width, hue, 0, 0), radius 0 for none. */
    fun pack(out: FloatArray, travel: Double) {
        for (i in 0 until SLOTS) {
            val o = i * 8
            java.util.Arrays.fill(out, o, o + 8, 0f)
            if (z[i].isNaN() || x[i].isNaN()) continue
            out[o] = (z[i] - travel).toFloat()
            out[o + 1] = x[i] + offX[i]
            out[o + 2] = y[i] + offY[i]
            out[o + 3] = radius[i]
            out[o + 4] = width[i]
            out[o + 5] = hue[i]
        }
    }

    companion object {
        const val SLOTS = 6
        const val STRAIGHT = 1
        const val CORKSCREW = 2
        const val NARROWING = 3
        const val LONG = 4
        const val CURVE = 5
    }
}
