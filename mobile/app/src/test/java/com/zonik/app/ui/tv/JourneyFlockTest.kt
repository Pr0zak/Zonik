package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.sqrt

class JourneyFlockTest {

    private class Run(seed: Int = 11) {
        val flock = JourneyFlock(seed)
        val path = JourneyPath()
        var travel = 0.0
        var nearest = 99f

        fun fly(seconds: Float, speed: Float = 1.2f, low: Float = 0.4f, kick: (Int) -> Float = { 0f }) {
            val steps = (seconds / 0.016f).toInt()
            for (k in 0 until steps) {
                val camZ = travel % JourneyPath.PERIOD
                val cx = path.xAt(camZ)
                val cy = JourneyPath.baseY(camZ).toFloat()
                flock.update(0.016f, travel, camZ, cx, cy, speed, 12f, low, kick(k), path)
                for (i in 0 until flock.size) {
                    val (x, y, z) = flock.position(i, travel)
                    val d = sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy) + z * z)
                    nearest = minOf(nearest, d)
                }
                travel += speed * 0.016
            }
        }

        /** Mean distance of school 0's fish from their middle. */
        fun spread(): Float {
            var cx = 0f; var cy = 0f; var cz = 0f
            val n = JourneyFlock.PER_SCHOOL
            for (i in 0 until n) { val (x, y, z) = flock.position(i, travel); cx += x; cy += y; cz += z }
            cx /= n; cy /= n; cz /= n
            var s = 0f
            for (i in 0 until n) { val (x, y, z) = flock.position(i, travel); s += sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy) + (z - cz) * (z - cz)) }
            return s / n
        }
    }

    @Test
    fun `schools stay near the path, ahead of or just behind the camera, for minutes`() {
        val r = Run()
        r.fly(180f)
        for (i in 0 until r.flock.size) {
            val (x, y, z) = r.flock.position(i, r.travel)
            assertTrue("x $x", !x.isNaN() && abs(x) < 4f)
            assertTrue("y $y", !y.isNaN() && abs(y) < 3f)
            assertTrue("z $z", z > -3f && z < 16f)
        }
    }

    @Test
    fun `the camera catches schools up and they dart out of its way`() {
        val r = Run()
        r.fly(120f)
        // It passed close by some, but never right through a fish.
        assertTrue("nearest ${r.nearest}", r.nearest < 1.2f)
        assertTrue("nearest ${r.nearest}", r.nearest > 0.03f)
    }

    @Test
    fun `a kick scatters the school, and it gathers again`() {
        val r = Run()
        r.fly(4f)
        val calm = r.spread()
        r.fly(0.3f, kick = { if (it == 0) 1f else 0f })
        val scattered = r.spread()
        assertTrue("calm $calm scattered $scattered", scattered > calm * 1.3f)
        r.fly(3f)
        assertTrue("gathered ${r.spread()}", r.spread() < scattered)
    }

    @Test
    fun `dashes are whole triangles on screen with depth in range`() {
        val r = Run()
        r.fly(3f)
        val cam = JourneyCamera()
        val camZ = r.travel % JourneyPath.PERIOD
        cam.update(0.016f, camZ, r.path)
        val basis = FloatArray(6)
        cam.basis(0f, basis)
        val out = FloatArray(JourneyFlock.MAX_VERTICES * JourneyFlock.FLOATS)
        val v = r.flock.build(out, r.travel, cam.pos, cam.fw, basis, 16f / 9f, 0f, 0f, 12f, 1f)
        assertTrue("$v vertices", v > 0)
        assertEquals(0, v % 6)
        for (k in 0 until v) {
            val o = k * JourneyFlock.FLOATS
            assertTrue(abs(out[o]) < 1.5f && abs(out[o + 1]) < 1.5f)
            assertTrue(out[o + 4] > 0f && out[o + 4] <= 12f / JourneyFlock.DEPTH_RANGE)
        }
    }
}
