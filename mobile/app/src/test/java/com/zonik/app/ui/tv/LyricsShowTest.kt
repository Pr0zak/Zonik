package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LyricsShowTest {
    private val song = TrackLyrics(
        "t",
        listOf(
            LyricLine(1_000, "I see the fireworks over the city"),
            LyricLine(3_000, "Dancing in the midnight, fireworks"),
            LyricLine(5_000, "Oh yeah the fucking fireworks"),
            LyricLine(7_000, "and you and I"),
            LyricLine(9_000, "Electric hearts are burning"),
        ),
        synced = true,
    )

    private fun run(show: LyricsShow, mode: Int = 1, rate: Int = 2, clean: Boolean = false, untilMs: Long = 11_000): List<String> {
        val shown = mutableListOf<String>()
        var pos = 0L
        while (pos < untilMs) {
            if (show.update(0.016f, pos, true, null, pos, mode, rate, 0, clean)) shown += show.text!!
            pos += 16
        }
        return shown
    }

    @Test
    fun `timed lyrics throw a strong word as each line starts`() {
        val show = LyricsShow(); show.setLyrics(song)
        val words = run(show)
        assertTrue("$words", words.size >= 3)
        // No filler words, and never from the all-filler line.
        assertTrue(words.none { it.lowercase() in setOf("the", "and", "you", "yeah", "over") })
        assertTrue("$words", words.all { it == it.uppercase() && it.length >= 3 })
    }

    @Test
    fun `the chorus word is favoured, clean leaves explicit words out, off shows nothing`() {
        val picks = List(200) { LyricsShow(it).also { s -> s.setLyrics(song) }.pickWord("Oh yeah the fucking fireworks", clean = true) }
        assertTrue(picks.none { it != null && LyricsShow.explicit(it) })
        assertEquals("fireworks", picks.groupingBy { it }.eachCount().maxBy { it.value }.key)
        val off = LyricsShow(); off.setLyrics(song)
        assertTrue(run(off, mode = 0).isEmpty())
    }

    @Test
    fun `whole lines come as they are sung, cleaned`() {
        val show = LyricsShow(); show.setLyrics(song)
        val lines = run(show, mode = 2, clean = true)
        assertTrue(lines.isNotEmpty())
        assertTrue(lines.none { it.contains("fucking") })
        assertTrue(show.isLine)
    }

    @Test
    fun `untimed lyrics land on bars`() {
        val show = LyricsShow()
        show.setLyrics(song.copy(lines = song.lines.map { it.copy(ms = -1) }, synced = false))
        val clock = BeatClock(120f, BeatGrid(120f, 0f, 4, drops = emptyList())).also { it.syncPosition(0, 0) }
        var count = 0
        var t = 0L
        while (t < 60_000) {
            if (show.update(0.016f, t, true, clock, t, 1, 1, 0, false)) count++
            t += 16
        }
        // Every 8 beats (4 s at 120 BPM), when a word is picked.
        assertTrue("$count", count in 8..16)
        assertNull(LyricsShow().pickWord("and you and I", false))
    }
}
