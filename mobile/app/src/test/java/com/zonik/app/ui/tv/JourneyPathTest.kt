package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class JourneyPathTest {

    private fun snapshot(p: JourneyPath) = DoubleArray(p.size) { p.levelAt(p.sampleZ(it)).toDouble() }

    @Test
    fun `a turn never touches what the camera can see`() {
        val p = JourneyPath()
        val camZ = 5.0
        val before = (0..60).map { p.xAt(camZ - 0.3 + it * 0.1) }
        assertTrue(p.turn(camZ, camZ + 7.0, 1.5f))
        val after = (0..60).map { p.xAt(camZ - 0.3 + it * 0.1) }
        // From just behind the camera to 5.7 units ahead (past the fog), nothing moved.
        before.zip(after).forEach { (a, b) -> assertEquals(a, b, 1e-6f) }
    }

    @Test
    fun `the path swerves to the new offset and holds it`() {
        val p = JourneyPath()
        p.turn(camZ = 0.0, startZ = 7.0, target = 1.5f)
        assertEquals(0f, p.levelAt(6.5), 1e-4f)
        assertEquals(1.5f, p.levelAt(10.0), 1e-3f)
        assertEquals(1.5f, p.levelAt(14.0), 1e-3f)
    }

    @Test
    fun `the ring stays continuous all the way round`() {
        val p = JourneyPath()
        p.turn(0.0, 7.0, 2.0f)
        p.turn(3.0, 12.0, -1.0f)
        val z = DoubleArray(4000) { it * JourneyPath.PERIOD / 4000 }
        var maxStep = 0f
        for (i in z.indices) {
            val a = p.levelAt(z[i])
            val b = p.levelAt(z[(i + 1) % z.size] + if (i + 1 == z.size) JourneyPath.PERIOD else 0.0)
            maxStep = maxOf(maxStep, abs(b - a))
        }
        // 4000 steps round 6π: a sharp turn of 3 units over 1.6 moves well under 0.02 a step.
        assertTrue("largest step $maxStep", maxStep < 0.03f)
    }

    @Test
    fun `turns too close to the camera are refused`() {
        val p = JourneyPath()
        val before = snapshot(p)
        assertFalse(p.turn(0.0, 3.0, 1f))
        assertFalse(p.turn(0.0, JourneyPath.PERIOD - 1.0, 1f))
        assertTrue(before.contentEquals(snapshot(p)))
    }

    @Test
    fun `the camera banks into a curve`() {
        val p = JourneyPath()
        p.turn(0.0, 7.0, 1.5f)
        val inTurn = p.bankAt(7.4)
        assertTrue("bank $inTurn", abs(inTurn) > 0.05f)
        assertTrue(abs(inTurn) <= JourneyPath.MAX_BANK)
    }

    @Test
    fun `motion keeps the path bounded and moves the look along`() {
        val p = JourneyPath()
        val m = JourneyMotion(seed = 3)
        val grid = BeatGrid(120f, 0f, 4, emptyList(), barEnergy = List(200) { 0.8f })
        val clock = BeatClock(120f, grid)
        clock.syncPosition(0, 0)
        var camZ = 0.0
        var t = 0L
        var maxLevel = 0f
        var styles = mutableSetOf<Float>()
        while (t < 180_000) {
            m.update(clock, t, 0.016f, camZ, 1.2f, p)
            camZ += 1.2 * 0.016
            maxLevel = maxOf(maxLevel, abs(p.levelNow(camZ)))
            styles += m.style
            t += 16
        }
        assertTrue("turns placed: ${p.version}", p.version >= 6)
        assertTrue(maxLevel <= JourneyPath.MAX_LEVEL + 1e-3f)
        assertTrue(m.hue > 1f) // stepped round at every 16 beats for 3 minutes
        assertTrue(0f in styles && 1f in styles)
        assertEquals(0.8f, m.energy, 0.01f)
    }
}
