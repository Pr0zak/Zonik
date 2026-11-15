package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BeatClockTest {

    // 120 BPM: a beat is 500 ms, a bar 2 s. The first downbeat is 1.25 s into the track; drops
    // at bars 8 and 40.
    private val grid = BeatGrid(bpm = 120f, downbeatMs = 1250f, beatsPerBar = 4, drops = listOf(8, 40))

    @Test
    fun `position sync puts beat 0 on the first downbeat`() {
        val clock = BeatClock(118f, grid)
        assertFalse(clock.synced)
        // 3.25 s into the track at wall time 100 000: 2 s after the downbeat, so beat 4.
        clock.syncPosition(positionMs = 3_250, nowMs = 100_000)
        assertTrue(clock.synced)
        assertEquals(4.0, clock.beatAt(100_000), 1e-6)
        assertEquals(500f, clock.beatMs, 1e-3f) // the grid's tempo wins over the stored one
        assertEquals(0f, clock.progressAt(100_000), 1e-6f)
        assertEquals(250f, clock.msToNextBeat(100_250), 1e-3f)
    }

    @Test
    fun `phrase boundaries count from the downbeat`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 3_250, nowMs = 100_000) // beat 4
        // Next multiple of 32 beats is beat 32: 28 beats = 14 s away.
        assertEquals(14_000f, clock.msToNextMultiple(100_000, 32), 1e-2f)
        // At least 20 s away: beat 32 is too soon, so beat 64 (60 beats = 30 s).
        assertEquals(30_000f, clock.msToNextMultiple(100_000, 32, minMs = 20_000f), 1e-2f)
    }

    @Test
    fun `drops are found inside the window only`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 3_250, nowMs = 100_000) // beat 4 = bar 1
        // Bar 8 is beat 32: 14 s away.
        assertEquals(14_000f, clock.msToDrop(100_000, 10_000f, 20_000f)!!, 1e-2f)
        // Bar 40 (beat 160) is 78 s away, outside 20-50 s.
        assertNull(clock.msToDrop(100_000, 20_000f, 50_000f))
    }

    @Test
    fun `a seek moves the grid with the player`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 3_250, nowMs = 100_000)
        clock.syncPosition(positionMs = 61_250, nowMs = 101_000) // jumped to 1:01.25
        assertEquals(120.0, clock.beatAt(101_000), 1e-6)
    }

    @Test
    fun `onsets correct a synced grid only a little`() {
        val clock = BeatClock(120f, grid)
        clock.syncPosition(positionMs = 3_250, nowMs = 100_000)
        // Every onset lands 100 ms late; the correction stops at 60 ms.
        repeat(40) { i -> clock.onOnset(100_000L + i * 500L + 100L) }
        val error = clock.progressAt(100_100) * 500f
        assertEquals(40f, error, 1f)
    }

    @Test
    fun `without a grid the clock locks to onsets as before`() {
        val clock = BeatClock(120f)
        assertNull(clock.msToDrop(0, 0f, 1e9f))
        clock.onOnset(10_000)
        assertEquals(0f, clock.progressAt(10_000), 1e-6f)
        assertFalse(clock.synced)
        clock.syncPosition(5_000, 20_000) // ignored without a grid
        assertFalse(clock.synced)
    }
}
