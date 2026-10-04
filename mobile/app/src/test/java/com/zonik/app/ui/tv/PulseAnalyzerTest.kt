package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PulseAnalyzerTest {

    /** A 1024-point capture at 48 kHz: 512 bins of ~47 Hz, the low band is bins 1..3. */
    private fun frame(low: Int, mid: Int = 20): ByteArray {
        val fft = ByteArray(1024)
        for (b in 1..3) fft[2 * b] = low.toByte()
        for (b in 7..42) fft[2 * b] = mid.toByte()
        return fft
    }

    private fun countOnsets(frames: List<ByteArray>): Int {
        val analyzer = PulseAnalyzer(48_000)
        var last = 0f
        var count = 0
        for (f in frames) {
            val p = analyzer.process(f)
            if (p.onset > 0.9f && last <= 0.9f) count++
            last = p.onset
        }
        return count
    }

    @Test
    fun `constant bass fires nothing`() {
        assertEquals(0, countOnsets(List(200) { frame(low = 60) }))
    }

    @Test
    fun `kicks over a bass line each fire once`() {
        // 120 BPM at 20 captures a second: a kick every 10 captures, 20 kicks.
        val frames = List(200) { i -> frame(low = if (i % 10 == 0) 120 else 50) }
        val onsets = countOnsets(frames)
        // The first few land during warm-up, before there is any history to judge against.
        assertTrue("got $onsets onsets", onsets in 17..20)
    }

    @Test
    fun `quiet track still registers its kicks`() {
        val frames = List(200) { i -> frame(low = if (i % 10 == 0) 12 else 4, mid = 3) }
        assertTrue(countOnsets(frames) >= 17)
    }

    @Test
    fun `beat clock nudges toward on-grid onsets and ignores one off-beat`() {
        val clock = BeatClock(120f) // 500 ms period
        clock.onOnset(1_000)
        clock.onOnset(1_540) // 40 ms late: pulled partway
        val p = clock.progressAt(1_540)
        assertTrue("progress $p", p > 0.0f && p < 0.08f)
        clock.onOnset(1_790) // half a beat off: ignored
        assertTrue(clock.progressAt(2_040) < 0.08f)
    }
}
