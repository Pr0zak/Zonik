package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class JourneySequencerTest {

    private val worlds = JOURNEY_WORLDS
    private val grid = BeatGrid(bpm = 120f, downbeatMs = 0f, beatsPerBar = 4, drops = emptyList())

    /** Runs frames every 16 ms from [from] to [to]; returns each world change's time. */
    private fun run(
        seq: JourneySequencer, from: Long, to: Long, clock: BeatClock?,
        kickAt: (Long) -> Float = { 0f }, current: DemoEffect = seq.world ?: worlds.first(),
    ): List<Long> {
        val changes = mutableListOf<Long>()
        var shown = current
        var t = from
        while (t <= to) {
            seq.update(shown, worlds, 42, clock, t, kickAt(t), unitsPerSec = 2f, transitioning = false)
            if (seq.world != shown) {
                changes += t
                shown = seq.world!!
            }
            t += 16
        }
        return changes
    }

    @Test
    fun `a synced grid opens portals on phrase starts at least 20 s apart`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 1_000, nowMs = 0) // beat 2 at t=0
        val seq = JourneySequencer()
        val changes = run(seq, 0, 70_000, clock)
        // Phrases (32 beats = 16 s) start at beats 32, 64, 96...: t = 15 s, 31 s, 47 s, 63 s.
        // The first at least 20 s on is beat 64 (31 s), then beat 128 (63 s).
        assertEquals(2, changes.size)
        assertEquals(31_000.0, changes[0].toDouble(), 20.0)
        assertEquals(63_000.0, changes[1].toDouble(), 20.0)
    }

    @Test
    fun `a drop wins over the phrase`() {
        val drop = BeatGrid(120f, 0f, 4, drops = listOf(12)) // bar 12 = beat 48 = 24 s
        val clock = BeatClock(120f, drop)
        clock.syncPosition(positionMs = 0, nowMs = 0)
        val changes = run(JourneySequencer(), 0, 30_000, clock)
        assertEquals(24_000.0, changes.first().toDouble(), 20.0)
    }

    @Test
    fun `the gate closes in over the last bar`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 1_000, nowMs = 0)
        val seq = JourneySequencer()
        run(seq, 0, 28_000, clock)
        assertEquals(0f, seq.gate, 0f) // 3 s out: a bar is 2 s, so not yet
        run(seq, 28_016, 30_000, clock)
        assertEquals(2f * 1f, seq.gate, 0.05f) // 1 s left at 2 units/s
    }

    @Test
    fun `without a tempo the portal waits for a kick`() {
        // Due at 24 s; nothing happens before the kick.
        val early = run(JourneySequencer(), 0, 24_300, null)
        assertTrue(early.isEmpty())
        val seq2 = JourneySequencer()
        val c2 = run(seq2, 0, 26_000, null, kickAt = { t -> if (t in 24_400..24_420) 1f else 0f })
        assertEquals(1, c2.size)
        assertEquals(24_400.0, c2[0].toDouble(), 20.0)
        // No kick at all: it goes after 1.5 s of waiting.
        val c3 = run(JourneySequencer(), 0, 26_000, null)
        assertEquals(25_500.0, c3[0].toDouble(), 20.0)
    }

    @Test
    fun `a grid arriving later replans onto its phrases`() {
        val seq = JourneySequencer()
        run(seq, 0, 5_000, null) // planned for 24 s with no clock
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 5_000, nowMs = 5_000) // beat 10 at 5 s
        val changes = run(seq, 5_016, 40_000, clock)
        // First phrase start at least 20 s on from 5 s: beat 64 = 32 s.
        assertEquals(32_000.0, changes.first().toDouble(), 20.0)
    }

    @Test
    fun `a seek replans with the music`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 1_000, nowMs = 0)
        val seq = JourneySequencer()
        run(seq, 0, 10_000, clock) // planned for beat 64
        clock.syncPosition(positionMs = 200_000, nowMs = 10_016) // jumped well past it
        val changes = run(seq, 10_016, 50_000, clock)
        // Replanned from beat 400: next phrase start 20 s on is beat 448, 24 s after the seek.
        assertEquals(34_016.0, changes.first().toDouble(), 30.0)
    }

    @Test
    fun `one world means no gate and no portal`() {
        val seq = JourneySequencer()
        var t = 0L
        while (t < 60_000) {
            seq.update(DemoEffect.GYROID, listOf(DemoEffect.GYROID), 1, null, t, 1f, 2f, false)
            assertEquals(0f, seq.gate, 0f)
            assertEquals(DemoEffect.GYROID, seq.world)
            t += 16
        }
    }

    @Test
    fun `it starts in the world already on screen`() {
        val seq = JourneySequencer()
        seq.update(DemoEffect.PILLARS, worlds, 9, null, 0, 0f, 2f, false)
        assertEquals(DemoEffect.PILLARS, seq.world)
        val other = JourneySequencer()
        other.update(DemoEffect.TUNNEL, worlds, 9, null, 0, 0f, 2f, false)
        assertNotEquals(null, other.world)
    }
}
