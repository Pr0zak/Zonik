package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class JourneyLandmarksTest {

    private class Run(val open: Boolean, val clock: BeatClock? = null, seed: Int = 5, val world: JourneyWorld? = null) {
        val lm = JourneyLandmarks(seed)
        val path = JourneyPath()
        val out = FloatArray(JourneyLandmarks.SLOTS * 8)
        var travel = 0.0
        var t = 0L
        /** Every landmark the first time it is seen: (distance ahead when it appeared, type, travel). */
        val firstSeen = mutableListOf<Triple<Float, Int, Double>>()
        private val seenZ = mutableSetOf<Long>()

        fun fly(ms: Long, speed: Float = 1.2f) {
            val end = t + ms
            while (t < end) {
                if (world != null) lm.update(world, travel, travel % JourneyPath.PERIOD, speed, clock, t, 0.016f, path)
                else lm.update(open, travel, travel % JourneyPath.PERIOD, speed, clock, t, 0.016f, path)
                lm.pack(out, travel)
                for (i in 0 until JourneyLandmarks.SLOTS) {
                    val type = out[i * 8 + 1].toInt()
                    if (type < 0) continue
                    val z = Math.round((out[i * 8] + travel) * 1000)
                    if (seenZ.add(z)) firstSeen += Triple(out[i * 8], type, travel)
                }
                travel += speed * 0.016
                t += 16
            }
        }
    }

    @Test
    fun `enclosed worlds get no landmarks at all`() {
        val r = Run(open = false)
        r.fly(120_000)
        assertEquals(0, r.firstSeen.size)
    }

    @Test
    fun `open worlds get big structures, appearing beyond the fog`() {
        val r = Run(open = true)
        r.fly(180_000)
        assertTrue("${r.firstSeen.size} big", r.firstSeen.size >= 8)
        // Canyon spawns 13 units ahead, just past its fog.
        r.firstSeen.forEach { (ahead, type, _) ->
            assertTrue("appeared $ahead ahead", ahead >= 12f)
            assertTrue("type $type", type >= JourneyLandmarks.CRYSTAL)
        }
        assertTrue(r.firstSeen.map { it.second }.toSet().size >= 3) // a real mix
    }

    @Test
    fun `a drop brings a tunnel or a hollow sphere that the camera reaches on it`() {
        // 120 BPM: a bar is 2 s; the drop is bar 15, 30 s in.
        val clock = BeatClock(120f, BeatGrid(120f, 0f, 4, drops = listOf(15)))
        clock.syncPosition(0, 0)
        // The orbital station has tunnels and hollow spheres.
        val r = Run(open = true, clock = clock, world = JourneyWorld.of(DemoEffect.STATION))
        r.fly(16_000)
        val atDrop = r.firstSeen.filter { it.second == JourneyLandmarks.TUNNEL || it.second == JourneyLandmarks.SPHERE }
            .map { it.third + it.first } // where along the flight it stands
        // The camera, at 1.2 units/s, is 36 units along at 30 s.
        assertTrue("structures at $atDrop", atDrop.any { kotlin.math.abs(it - 36.0) < 0.3 })
    }

    @Test
    fun `passed landmarks free their slots`() {
        val r = Run(open = true)
        r.fly(600_000)
        assertTrue(r.lm.count <= JourneyLandmarks.SLOTS)
        // Ten minutes in, everything in the slots is still ahead of, or just passing, the camera.
        for (i in 0 until JourneyLandmarks.SLOTS) {
            if (r.out[i * 8 + 1] < 0) continue
            assertTrue(r.out[i * 8] > -6f)
        }
        assertEquals(true, r.firstSeen.size > 30)
    }

    @Test
    fun `a new world drops what the last one placed far ahead`() {
        val lm = JourneyLandmarks(3)
        val path = JourneyPath()
        val out = FloatArray(JourneyLandmarks.SLOTS * 8)
        var travel = 0.0
        repeat(600) {
            lm.update(true, travel, travel, 1.2f, null, it * 16L, 0.016f, path)
            travel += 1.2 * 0.016
        }
        lm.update(false, travel, travel, 1.2f, null, 10_000L, 0.016f, path)
        lm.pack(out, travel)
        for (i in 0 until JourneyLandmarks.SLOTS) {
            if (out[i * 8 + 1] < 0) continue
            assertTrue("${out[i * 8]} ahead", out[i * 8] <= 4f)
        }
    }
}
