package com.zonik.app.ui.tv

import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Schools of fish (or flocks of birds) in the open Journey worlds that have them
 * ([JourneyWorld.flock]): [SCHOOLS] schools of [PER_SCHOOL], steered on the CPU as boids and
 * drawn by the renderer as small glowing dashes, hidden behind rock by the world's depth.
 *
 * Each school follows an anchor that swims slowly along the path, a little to one side, so the
 * camera catches it up and flies past or through it; the fish nearest the camera dart out of
 * its way. Once the camera has passed a school it is placed again further ahead, in the fog.
 * Bass sets how fast they swim, and a kick scatters each school from its middle.
 *
 * Pure logic with no GL and no allocation per frame. Positions are x and y in the path's
 * coordinates and z along the flight ([travel], never wrapped), like the landmarks.
 */
class JourneyFlock(seed: Int = 11) {
    private val random = kotlin.random.Random(seed)
    private val n = SCHOOLS * PER_SCHOOL
    private val px = FloatArray(n)
    private val py = FloatArray(n)
    private val pz = DoubleArray(n)
    private val vx = FloatArray(n)
    private val vy = FloatArray(n)
    private val vz = FloatArray(n)
    /** Each school's anchor: z along the flight, offset from the path, hue and spectrum band. */
    private val anchorZ = DoubleArray(SCHOOLS) { Double.NaN }
    private val anchorX = FloatArray(SCHOOLS)
    private val anchorY = FloatArray(SCHOOLS)
    val hue = FloatArray(SCHOOLS)
    val band = FloatArray(SCHOOLS)
    private var lastKick = 0f

    /**
     * Jellyfish rather than fish: slow, spread out, drifting upward with a pulse on the beat,
     * drawn bigger and upright (the shader draws the bell and tentacles, uFlockStyle).
     */
    var jelly = false

    /** For tests: fish [i]'s position (x, y, z ahead of [travel]). */
    fun position(i: Int, travel: Double) = Triple(px[i], py[i], (pz[i] - travel).toFloat())
    val size: Int get() = n

    /** Forgets every school, so the next update places them all afresh (a new world). */
    fun reset() {
        java.util.Arrays.fill(anchorZ, Double.NaN)
    }

    /**
     * One step: [travel] the camera's distance along the flight, [camZ] its z on the path,
     * [camX]/[camY] its position, [cruise] the camera's speed in units a second, [far] the
     * world's fog distance, [low] the bass and [kick] the kick (each 0..1).
     */
    fun update(
        dt: Float, travel: Double, camZ: Double, camX: Float, camY: Float, cruise: Float,
        far: Float, low: Float, kick: Float, path: JourneyPath,
    ) {
        val h = dt.coerceIn(0f, 0.05f)
        val kicked = kick > 0.6f && lastKick <= 0.6f
        lastKick = kick
        for (s in 0 until SCHOOLS) {
            if (anchorZ[s].isNaN() || anchorZ[s] < travel - 1.5) place(s, travel, camZ, far, anchorZ[s].isNaN(), path)
            // The anchor swims at a fraction of the camera's speed, so the camera catches it up.
            anchorZ[s] += cruise * ANCHOR_SPEED * h
        }
        val maxSpeed = (0.35f + 0.6f * low) * cruise.coerceAtLeast(0.5f) * (if (jelly) 0.3f else 1f)
        val spacing = if (jelly) 0.5f else SPACING
        for (s in 0 until SCHOOLS) {
            val o = s * PER_SCHOOL
            // The school's middle and its heading.
            var cx = 0f; var cy = 0f; var cz = 0.0
            var ax = 0f; var ay = 0f; var az = 0f
            for (i in o until o + PER_SCHOOL) {
                cx += px[i]; cy += py[i]; cz += pz[i]
                ax += vx[i]; ay += vy[i]; az += vz[i]
            }
            val inv = 1f / PER_SCHOOL
            cx *= inv; cy *= inv; cz *= inv.toDouble()
            ax *= inv; ay *= inv; az *= inv
            val along = camZ + (anchorZ[s] - travel)
            val gx = path.xAt(along) + anchorX[s]
            val gy = JourneyPath.baseY(along).toFloat() + anchorY[s]
            for (i in o until o + PER_SCHOOL) {
                val rz = (pz[i] - cz).toFloat()
                // Toward the middle, with the school's heading, toward the anchor.
                // Jellyfish barely keep together: they drift as a loose bloom, not a school.
                val coh = if (jelly) COHESION * 0.08f else COHESION
                val goal = if (jelly) GOAL * 0.25f else GOAL
                var fx = (cx - px[i]) * coh + (ax - vx[i]) * ALIGN + (gx - px[i]) * goal
                var fy = (cy - py[i]) * coh + (ay - vy[i]) * ALIGN + (gy - py[i]) * goal
                var fz = -rz * coh + (az - vz[i]) * ALIGN + (anchorZ[s] - pz[i]).toFloat() * goal
                // Apart from close neighbours.
                for (j in o until o + PER_SCHOOL) {
                    if (j == i) continue
                    val dx = px[i] - px[j]
                    val dy = py[i] - py[j]
                    val dz = (pz[i] - pz[j]).toFloat()
                    val d2 = dx * dx + dy * dy + dz * dz
                    if (d2 < spacing * spacing && d2 > 1e-6f) {
                        val k = SEPARATE / d2
                        fx += dx * k; fy += dy * k; fz += dz * k
                    }
                }
                // Out of the camera's way.
                val ex = px[i] - camX
                val ey = py[i] - camY
                val ez = (pz[i] - travel).toFloat()
                val e2 = ex * ex + ey * ey + ez * ez
                if (e2 < DART * DART) {
                    val k = 6f / (e2 + 0.02f)
                    fx += ex * k; fy += ey * k; fz += abs(ez) * k * 0.3f
                }
                // A kick scatters the school from its middle.
                if (kicked) {
                    val sx = px[i] - cx
                    val sy = py[i] - cy
                    val l = sqrt(sx * sx + sy * sy + rz * rz).coerceAtLeast(0.02f)
                    val k = SCATTER * kick / l
                    vx[i] += sx * k; vy[i] += sy * k; vz[i] += rz * k
                }
                vx[i] += fx * h; vy[i] += fy * h; vz[i] += fz * h
                // Jellyfish rise in pulses, a push up with each kick.
                if (jelly && kicked) vy[i] += 0.15f
                val sp = sqrt(vx[i] * vx[i] + vy[i] * vy[i] + vz[i] * vz[i])
                if (sp > maxSpeed) {
                    val k = maxSpeed / sp
                    vx[i] *= k; vy[i] *= k; vz[i] *= k
                }
                // A little drag, so the school settles after a scatter.
                val drag = exp(-h * 0.6f)
                vx[i] *= drag; vy[i] *= drag; vz[i] *= drag
            }
            for (i in o until o + PER_SCHOOL) {
                px[i] += vx[i] * h
                py[i] += vy[i] * h
                pz[i] += vz[i] * h + cruise * ANCHOR_SPEED * h
            }
        }
    }

    private fun place(s: Int, travel: Double, camZ: Double, far: Float, first: Boolean, path: JourneyPath) {
        // A new world opens with the schools already in view; after that they appear in the fog.
        val ahead = if (first) far * (0.25f + 0.2f * s) else far * (0.8f + 0.2f * random.nextFloat())
        anchorZ[s] = travel + ahead
        val angle = random.nextFloat() * 2f * Math.PI.toFloat()
        val r = 0.3f + random.nextFloat() * 0.9f
        anchorX[s] = r * cos(angle)
        anchorY[s] = r * sin(angle) * 0.6f
        hue[s] = random.nextFloat()
        band[s] = (4 + random.nextInt(40)).toFloat()
        val o = s * PER_SCHOOL
        val along = camZ + ahead
        val bx = path.xAt(along) + anchorX[s]
        val by = JourneyPath.baseY(along).toFloat() + anchorY[s]
        // A school starts tight; jellyfish start scattered through a wide stretch of water.
        val sx = if (jelly) 3.0f else 0.6f
        val sy = if (jelly) 1.8f else 0.4f
        val sz = if (jelly) 6.0 else 0.8
        for (i in o until o + PER_SCHOOL) {
            px[i] = bx + (random.nextFloat() - 0.5f) * sx
            py[i] = by + (random.nextFloat() - 0.5f) * sy
            pz[i] = anchorZ[s] + (random.nextFloat() - 0.5f) * sz
            vx[i] = (random.nextFloat() - 0.5f) * 0.1f
            vy[i] = (random.nextFloat() - 0.5f) * 0.1f
            vz[i] = 0.1f
        }
    }

    /**
     * The fish as screen-space dashes, two triangles each, into [out] (8 floats a vertex:
     * NDC x, y; along, across in -1..1; distance / [DEPTH_RANGE], hue, spectrum band,
     * brightness), for a camera at [pos] (on the path at [camZ]) heading [fw] with right and up
     * in [basis], screen offset ([centerX], [centerY]) and [aspect]. Returns the vertex count.
     */
    fun build(
        out: FloatArray, travel: Double, pos: FloatArray, fw: FloatArray,
        basis: FloatArray, aspect: Float, centerX: Float, centerY: Float, far: Float, sizeScale: Float,
    ): Int {
        var v = 0
        for (i in 0 until n) {
            val rx = px[i] - pos[0]
            val ry = py[i] - pos[1]
            val rz = (pz[i] - travel).toFloat() - pos[2]
            val depth = rx * fw[0] + ry * fw[1] + rz * fw[2]
            if (depth < 0.15f) continue
            val dist = sqrt(rx * rx + ry * ry + rz * rz)
            if (dist > far) continue
            val sx = (rx * basis[0] + ry * basis[1] + rz * basis[2]) * 1.3f / depth
            val sy = (rx * basis[3] + ry * basis[4] + rz * basis[5]) * 1.3f / depth
            if (abs(sx) > aspect + 0.3f || abs(sy) > 1.3f) continue
            // Which way it swims on screen: a point a little ahead along its velocity (for a
            // jellyfish, straight up, so it is drawn upright).
            val qx = if (jelly) rx else rx + vx[i] * 0.2f
            val qy = if (jelly) ry + 0.2f else ry + vy[i] * 0.2f
            val qz = if (jelly) rz else rz + vz[i] * 0.2f
            val qd = (qx * fw[0] + qy * fw[1] + qz * fw[2]).coerceAtLeast(0.05f)
            var dx = (qx * basis[0] + qy * basis[1] + qz * basis[2]) * 1.3f / qd - sx
            var dy = (qx * basis[3] + qy * basis[4] + qz * basis[5]) * 1.3f / qd - sy
            val dl = sqrt(dx * dx + dy * dy)
            if (dl < 1e-4f) { dx = 1f; dy = 0f } else { dx /= dl; dy /= dl }
            // Longer when swimming across the view, never smaller than a few pixels.
            val w = (FISH_WIDTH * sizeScale * (if (jelly) 3.5f else 1f) * 1.3f / depth).coerceAtLeast(0.007f)
            val l = if (jelly) w * 1.6f else w * (1.5f + (dl * 6f).coerceAtMost(1.8f))
            val fog = 1f - smoothstep(far * 0.55f, far, dist)
            val s = i / PER_SCHOOL
            val glow = fog * (0.7f + 0.3f * sin(i * 1.7f))
            val c0 = (sx + centerX) / aspect
            val c1 = sy + centerY
            val ax = dx * l / aspect; val ay = dy * l
            val bx = -dy * w / aspect; val by = dx * w
            val d = dist / DEPTH_RANGE
            val hu = hue[s] + (i % PER_SCHOOL) * 0.004f
            v = vertex(out, v, c0 - ax - bx, c1 - ay - by, -1f, -1f, d, hu, band[s], glow)
            v = vertex(out, v, c0 + ax - bx, c1 + ay - by, 1f, -1f, d, hu, band[s], glow)
            v = vertex(out, v, c0 + ax + bx, c1 + ay + by, 1f, 1f, d, hu, band[s], glow)
            v = vertex(out, v, c0 - ax - bx, c1 - ay - by, -1f, -1f, d, hu, band[s], glow)
            v = vertex(out, v, c0 + ax + bx, c1 + ay + by, 1f, 1f, d, hu, band[s], glow)
            v = vertex(out, v, c0 - ax + bx, c1 - ay + by, -1f, 1f, d, hu, band[s], glow)
        }
        return v
    }

    private fun vertex(out: FloatArray, v: Int, x: Float, y: Float, u: Float, w: Float, d: Float, hu: Float, b: Float, g: Float): Int {
        val o = v * FLOATS
        out[o] = x; out[o + 1] = y; out[o + 2] = u; out[o + 3] = w
        out[o + 4] = d; out[o + 5] = hu; out[o + 6] = b; out[o + 7] = g
        return v + 1
    }

    private fun smoothstep(a: Float, b: Float, x: Float): Float {
        val t = ((x - a) / (b - a)).coerceIn(0f, 1f)
        return t * t * (3f - 2f * t)
    }

    companion object {
        const val SCHOOLS = 2
        const val PER_SCHOOL = 24
        const val FLOATS = 8
        /** Vertices for every fish: two triangles each. */
        const val MAX_VERTICES = SCHOOLS * PER_SCHOOL * 6
        /** The world's depth in the scene's alpha is distance / this (JDEPTH in JOURNEY_BODY). */
        const val DEPTH_RANGE = 20f
        private const val ANCHOR_SPEED = 0.35f
        private const val COHESION = 0.8f
        private const val ALIGN = 1.2f
        private const val GOAL = 0.35f
        private const val SEPARATE = 0.004f
        private const val SPACING = 0.12f
        private const val DART = 0.7f
        private const val SCATTER = 0.9f
        private const val FISH_WIDTH = 0.03f
    }
}
