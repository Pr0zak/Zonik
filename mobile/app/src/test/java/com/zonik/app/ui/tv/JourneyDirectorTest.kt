package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class JourneyDirectorTest {

    private class Run(val room: Boolean, val crane: Boolean, val clock: BeatClock? = null) {
        val d = JourneyDirector()
        var t = 0L
        val shots = mutableMapOf<Int, Int>()
        var drops = 0
        var mirrors = 0

        fun go(ms: Long, busy: Boolean = false, low: Float = 0.5f, kick: (Long) -> Float = { 0f }) {
            val end = t + ms
            var was = d.shot
            var mirror = d.mirror
            while (t < end) {
                val before = d.dropAge
                d.update(0.016f, clock, t, room, crane, shots = true, drops = true, mirrors = true, busy = busy,
                    low = low, kick = kick(t), energy = 0.5f)
                if (d.dropAge < before) drops++
                if (d.shot != was) { shots[d.shot] = (shots[d.shot] ?: 0) + 1; was = d.shot }
                if (d.mirror != 0 && mirror == 0) mirrors++
                mirror = d.mirror
                t += 16
            }
        }
    }

    private fun grid(drops: List<Int> = emptyList()): BeatClock =
        BeatClock(120f, BeatGrid(120f, 0f, 4, drops = drops)).also { it.syncPosition(0, 0) }

    @Test
    fun `open worlds get every shot, each back to the chase camera`() {
        val r = Run(room = true, crane = true, clock = grid())
        r.go(600_000)
        for (s in listOf(JourneyDirector.BACK, JourneyDirector.CRANE, JourneyDirector.SIDE)) {
            assertTrue("shot $s in ${r.shots}", (r.shots[s] ?: 0) >= 3)
        }
        // Mostly the chase camera, cutting back after every other shot.
        val others = r.shots.filterKeys { it != JourneyDirector.CHASE }.values.sum()
        assertEquals(others, r.shots[JourneyDirector.CHASE] ?: 0, 1f)
    }

    private fun assertEquals(a: Int, b: Int, slack: Float) = assertTrue("$a vs $b", abs(a - b) <= slack)

    @Test
    fun `the enclosed worlds only look back, and a portal keeps the chase camera`() {
        val r = Run(room = false, crane = false, clock = grid())
        r.go(300_000)
        assertTrue(r.shots.keys.all { it == JourneyDirector.BACK || it == JourneyDirector.CHASE })
        assertTrue((r.shots[JourneyDirector.BACK] ?: 0) > 0)
        val b = Run(room = true, crane = true, clock = grid())
        b.go(120_000, busy = true)
        assertEquals(JourneyDirector.CHASE, b.d.shot)
        assertTrue(b.shots.isEmpty())
    }

    @Test
    fun `a drop on the grid fires once, cuts to the crane and flashes`() {
        // Drop at bar 10: beat 40, 20 s in at 120 BPM.
        val r = Run(room = true, crane = true, clock = grid(drops = listOf(10)))
        r.go(19_000)
        assertEquals(0, r.drops)
        r.go(1_400)
        assertEquals(1, r.drops)
        assertEquals(JourneyDirector.CRANE, r.d.shot)
        assertTrue(r.d.invert > 0.9f)
        r.go(5_000)
        assertEquals(1, r.drops)
        assertEquals(0f, r.d.invert, 0f)
        assertTrue(r.d.flash < 0.01f)
    }

    @Test
    fun `without a grid a big bass entry after a quiet stretch is the drop`() {
        val r = Run(room = true, crane = true)
        r.go(10_000, low = 0.1f)
        assertEquals(0, r.drops)
        r.go(500, low = 0.8f, kick = { 1f })
        assertEquals(1, r.drops)
    }

    @Test
    fun `mirror bars come now and then and last a block`() {
        val r = Run(room = true, crane = true, clock = grid())
        r.go(600_000)
        assertTrue("${r.mirrors} mirror bars", r.mirrors in 3..40)
    }

    @Test
    fun `shots stay at z 0, the crane rises above the path and looking back turns round`() {
        val path = JourneyPath()
        val cam = JourneyCamera()
        cam.update(0.016f, 5.0, path)
        val out = JourneyCamera()
        val r = Run(room = true, crane = true, clock = grid())
        var seen = 0
        while (seen != 0b111 && r.t < 900_000) {
            r.go(200)
            r.d.apply(cam, out, path, 5.0)
            assertEquals(0f, out.pos[2], 0f)
            when (r.d.shot) {
                JourneyDirector.BACK -> { assertTrue(out.fw[2] < -0.5f); seen = seen or 1 }
                JourneyDirector.CRANE -> { assertTrue(out.pos[1] > cam.pos[1] + 0.2f); assertTrue(out.fw[1] < 0f); seen = seen or 2 }
                JourneyDirector.SIDE -> { assertTrue(abs(out.pos[0] - cam.pos[0]) > 0.25f); seen = seen or 4 }
            }
        }
        assertEquals(0b111, seen)
    }

    @Test
    fun `weather only where it makes sense`() {
        assertEquals(0, JourneyDirector.weatherIn(DemoEffect.ABYSS, JourneyDirector.RAIN))
        assertEquals(0, JourneyDirector.weatherIn(DemoEffect.GYROID, JourneyDirector.SNOW))
        assertEquals(JourneyDirector.SNOW, JourneyDirector.weatherIn(DemoEffect.TUNDRA, JourneyDirector.RAIN))
        assertEquals(JourneyDirector.RAIN, JourneyDirector.weatherIn(DemoEffect.CYBER, JourneyDirector.SNOW))
        assertEquals(JourneyDirector.FOG, JourneyDirector.weatherIn(DemoEffect.CANYON, JourneyDirector.FOG))
    }
}

class JourneyBoardTest {
    @Test
    fun `a new track puts its title up first, then covers now and then`() {
        val b = JourneyBoard()
        val path = JourneyPath()
        var travel = 0.0
        val kinds = mutableListOf<Int>()
        var up = false
        val out = FloatArray(8)
        for (i in 0 until 60 * 180) {
            b.update(1f / 60f, travel, 13.0, room = true, on = true, title = "Song")
            val a = b.ahead(travel)
            if (a != null && !up) kinds += b.kind
            up = a != null
            b.pack(out, travel, travel % JourneyPath.PERIOD, path)
            if (a != null && a > 0.05) assertTrue(out[3] > 0f && abs(out[1]) > 1f)
            travel += 1.2 / 60.0
        }
        assertEquals(JourneyBoard.TITLE, kinds.first())
        assertTrue("$kinds", kinds.drop(1).all { it == JourneyBoard.COVER } && kinds.size in 3..8)
        val off = JourneyBoard()
        repeat(600) { off.update(0.1f, 0.0, 13.0, room = false, on = true, title = "Song") }
        assertEquals(null, off.ahead(0.0))
    }
}
