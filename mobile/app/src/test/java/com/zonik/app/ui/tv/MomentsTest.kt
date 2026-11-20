package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MomentsTest {

    private fun grid(drops: List<Int> = emptyList(), energy: List<Float> = emptyList()): BeatClock =
        BeatClock(120f, BeatGrid(120f, 0f, 4, drops = drops, barEnergy = energy)).also { it.syncPosition(0, 0) }

    private class Run(val m: Moments = Moments(), val clock: BeatClock? = null) {
        var t = 0L
        var maxEnv = 0f
        var wasNone = true
        val seenSpeeds = mutableSetOf<Float>()

        fun go(ms: Long, mode: Int = 2, rate: Int = 1, world: Boolean = true, glimpses: Boolean = true,
               low: (Long) -> Float = { 0.5f }, kick: (Long) -> Float = { if (it % 500 < 20) 1f else 0f }) {
            val end = t + ms
            while (t < end) {
                m.update(0.016f, clock, t, low(t), kick(t), world, mode, rate, glimpses, busy = false)
                maxEnv = maxOf(maxEnv, m.env)
                // Every moment starts from nothing and eases in.
                if (wasNone && m.kind != Moments.NONE) assertTrue("kind ${m.kind} starts at ${m.env} t=$t", m.env < 0.5f)
                wasNone = m.kind == Moments.NONE
                seenSpeeds += m.speedScale
                assertTrue(m.env in 0f..1f)
                t += 16
            }
        }
        fun count(kinds: Collection<Int>) = kinds.sumOf { m.started[it] }
    }

    @Test
    fun `off means none, subtle only subtle, striking only striking`() {
        val off = Run(clock = grid()); off.go(300_000, mode = 0)
        assertEquals(0, off.m.started.sum())
        val subtle = Run(clock = grid()); subtle.go(600_000, mode = 1)
        assertTrue(subtle.count(Moments.SUBTLE) >= 20)
        assertEquals(0, subtle.count(Moments.STRIKING))
        val striking = Run(clock = grid()); striking.go(600_000, mode = 3)
        assertTrue("${striking.m.started.toList()}", striking.count(Moments.STRIKING) >= 12)
        assertEquals(0, striking.count(Moments.SUBTLE))
    }

    @Test
    fun `mixed has both, and the rate setting changes how many`() {
        val rare = Run(clock = grid()); rare.go(600_000, rate = 0)
        val often = Run(clock = grid()); often.go(600_000, rate = 2)
        assertTrue(often.count(Moments.SUBTLE) > 0 && often.count(Moments.STRIKING) > 0)
        assertTrue("rare ${rare.m.started.sum()} often ${often.m.started.sum()}", often.m.started.sum() > rare.m.started.sum() * 1.5)
    }

    @Test
    fun `outside a world and without glimpses the world moments never come`() {
        val r = Run(clock = grid()); r.go(900_000, mode = 3, world = false)
        assertEquals(0, r.count(Moments.WORLD_ONLY))
        assertTrue(r.count(Moments.STRIKING) > 5)
        val g = Run(clock = grid()); g.go(900_000, mode = 3, glimpses = false)
        assertEquals(0, g.count(listOf(Moments.GLIMPSE, Moments.GHOST)))
    }

    @Test
    fun `a drop on the grid sets one off around it`() {
        // A drop at bar 20 (beat 80, 40 s).
        val r = Run(clock = grid(drops = listOf(20)))
        r.go(38_500, mode = 3, rate = 0)
        val before = r.m.started.sum()
        r.go(2_200, mode = 3, rate = 0)
        assertTrue("before $before after ${r.m.started.sum()}", r.m.started.sum() > before)
    }

    @Test
    fun `speed stays within slow motion, stutter and rewind`() {
        val r = Run(clock = grid()); r.go(900_000, mode = 3, rate = 2)
        assertTrue(r.seenSpeeds.all { it in -1.11f..2.61f })
        assertTrue(r.maxEnv > 0.99f)
    }
}
