package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs
import kotlin.math.acos

class JourneyCameraTest {

    private fun angle(a: FloatArray, b: FloatArray) =
        acos((a[0] * b[0] + a[1] * b[1] + a[2] * b[2]).coerceIn(-1f, 1f))

    @Test
    fun `the heading turns smoothly through a swerve`() {
        val path = JourneyPath()
        path.turn(0.0, 8.0, 1.6f)
        val cam = JourneyCamera()
        var z = 0.0
        val prev = FloatArray(3)
        var maxStep = 0f
        repeat(900) { // 15 s at 60 fps, 1.2 units/s: through the swerve and out
            cam.fw.copyInto(prev)
            cam.update(1f / 60f, z, path)
            if (it > 0) maxStep = maxOf(maxStep, angle(prev, cam.fw))
            z += 1.2 / 60
        }
        // Never more than about 0.6 degrees of turn in one frame.
        assertTrue("max step $maxStep rad", maxStep < 0.011f)
    }

    @Test
    fun `the basis stays square for any roll`() {
        val path = JourneyPath()
        val cam = JourneyCamera()
        cam.update(0.016f, 3.0, path)
        val b = FloatArray(6)
        for (roll in listOf(0f, 0.7f, -2.1f, 3.1f)) {
            cam.basis(roll, b)
            val rt = floatArrayOf(b[0], b[1], b[2])
            val up = floatArrayOf(b[3], b[4], b[5])
            assertEquals(0f, rt[0] * up[0] + rt[1] * up[1] + rt[2] * up[2], 1e-4f)
            assertEquals(0f, rt[0] * cam.fw[0] + rt[1] * cam.fw[1] + rt[2] * cam.fw[2], 1e-4f)
            assertEquals(1f, rt[0] * rt[0] + rt[1] * rt[1] + rt[2] * rt[2], 1e-4f)
            assertEquals(1f, up[0] * up[0] + up[1] * up[1] + up[2] * up[2], 1e-4f)
        }
    }

    @Test
    fun `a landmark ahead projects onto the screen, one behind does not`() {
        val path = JourneyPath()
        val cam = JourneyCamera()
        cam.update(0.016f, 0.0, path)
        val b = FloatArray(6)
        cam.basis(0f, b)
        val lm = JourneyLandmarks(seed = 2)
        val out = FloatArray(JourneyLandmarks.SLOTS * 4)
        var travel = 0.0
        repeat(2000) {
            lm.update(open = true, travel = travel, camZ = travel, unitsPerSec = 1.2f, clock = null, nowMs = it * 16L, dt = 0.016f, path = path)
            travel += 1.2 * 0.016
        }
        cam.update(0.016f, travel % JourneyPath.PERIOD, path)
        cam.basis(0f, b)
        lm.screen(out, travel, cam.pos, cam.fw, b)
        val packed = FloatArray(JourneyLandmarks.SLOTS * 8)
        lm.pack(packed, travel)
        for (i in 0 until JourneyLandmarks.SLOTS) {
            val ahead = packed[i * 8]
            val type = packed[i * 8 + 1]
            if (type < 0) assertEquals(0f, out[i * 4 + 2], 0f)
            else if (ahead > 3f) assertTrue("slot $i radius ${out[i * 4 + 2]}", out[i * 4 + 2] in 0.01f..98f && abs(out[i * 4]) < 50f)
        }
    }
}
