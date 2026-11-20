package com.zonik.app.ui.tv

/** One line of a track's lyrics; [ms] is -1 when the lyrics are untimed. */
data class LyricLine(val ms: Long, val text: String)

/** A track's lyrics as the TV has them. */
data class TrackLyrics(val trackId: String, val lines: List<LyricLine>, val synced: Boolean)

/**
 * Lyrics flying at the viewer: picks a word (or the whole line) from the song and how it
 * arrives, and times it. With timed lyrics a word comes as its line is sung; with untimed
 * ones, a random line's word lands on a bar. Short filler words are skipped; longer words and
 * the ones the song repeats (the chorus) are favoured. Pure logic, no GL: the renderer draws
 * [text] in [style] at [t] (0..1 through its life).
 */
class LyricsShow(seed: Int = 71) {
    private val random = kotlin.random.Random(seed)
    private var lines: List<LyricLine> = emptyList()
    private var synced = false
    private var counts: Map<String, Int> = emptyMap()
    private var lineIdx = -1
    private var lastPos = -1L
    private var wait = 3f
    private var lastBar = Long.MIN_VALUE
    private var lastStyle = 0

    /** The text up now (upper case for words), or null. */
    var text: String? = null
        private set
    var style = HURL
        private set
    /** 0..1 through its life. */
    var t = 0f
        private set
    /** A random value per showing (side, colour). */
    var param = 0f
        private set
    /** Whether it is a whole line (drawn smaller). */
    var isLine = false
        private set
    private var age = 0f
    private var life = 2f

    val active: Boolean get() = text != null

    fun setLyrics(l: TrackLyrics?) {
        lines = l?.lines?.filter { it.text.isNotBlank() } ?: emptyList()
        synced = l?.synced == true && lines.any { it.ms >= 0 }
        counts = lines.flatMap { words(it.text) }.groupingBy { it.lowercase() }.eachCount()
        lineIdx = -1
        lastPos = -1L
        text = null
    }

    /**
     * One frame. Returns true when new text has started (the renderer draws it into its
     * texture). [positionMs] is the playback position now, or null when unknown.
     */
    fun update(
        dt: Float, positionMs: Long?, playing: Boolean, clock: BeatClock?, nowMs: Long,
        mode: Int, rate: Int, styleOption: Int, clean: Boolean,
    ): Boolean {
        if (text != null) {
            age += dt
            t = (age / life).coerceIn(0f, 1f)
            if (age >= life) text = null
        }
        if (mode == 0 || lines.isEmpty() || !playing) {
            if (mode == 0) text = null
            return false
        }
        val chance = when (rate) { 0 -> 0.3f; 2 -> 1f; else -> 0.6f }
        if (synced && positionMs != null) {
            // The line being sung: a seek back starts the search again.
            if (positionMs < lastPos - 1500 || lineIdx < 0) lineIdx = lines.indexOfLast { it.ms in 0..positionMs }
            lastPos = positionMs
            var started = -1
            while (lineIdx + 1 < lines.size && lines[lineIdx + 1].ms in 0..positionMs) {
                lineIdx++
                started = lineIdx
            }
            if (started < 0 || text != null) return false
            if (random.nextFloat() > chance) return false
            val next = lines.getOrNull(started + 1)?.ms?.takeIf { it > lines[started].ms }
            val gapSec = next?.let { (it - lines[started].ms) / 1000f } ?: 4f
            return show(lines[started].text, mode, styleOption, clean, gapSec)
        }
        // Untimed: a random line's word, on a bar every so often.
        if (text != null) return false
        val tempo = clock?.takeIf { it.hasTempo }
        if (tempo != null) {
            val every = when (rate) { 0 -> 16; 2 -> 4; else -> 8 }
            val bar = kotlin.math.floor(tempo.beatAt(nowMs) / every).toLong()
            if (bar == lastBar) return false
            lastBar = bar
        } else {
            wait -= dt
            if (wait > 0f) return false
            wait = when (rate) { 0 -> 9f; 2 -> 2.5f; else -> 5f }
        }
        val line = lines[random.nextInt(lines.size)]
        return show(line.text, mode, styleOption, clean, 3f)
    }

    private fun show(line: String, mode: Int, styleOption: Int, clean: Boolean, gapSec: Float): Boolean {
        val chosen = if (mode == 2) {
            val l = if (clean) clean(line) else line
            l.take(60).trim().takeIf { it.isNotEmpty() }
        } else {
            pickWord(line, clean)?.uppercase()
        } ?: return false
        style = if (styleOption in 1..STYLES) styleOption else {
            var s: Int
            do { s = 1 + random.nextInt(STYLES) } while (s == lastStyle && STYLES > 1)
            s
        }
        lastStyle = style
        text = chosen
        isLine = mode == 2
        param = random.nextFloat()
        age = 0f
        t = 0f
        val base = when (style) { BACKDROP -> 3.6f; NEON -> 2.6f; EXPLODE -> 2.4f; ECHO -> 2.2f; else -> 1.9f }
        life = if (isLine) gapSec.coerceIn(1.6f, 5f) else base
        return true
    }

    /** The word to throw from a line: no filler, favouring long words and the chorus's. */
    fun pickWord(line: String, clean: Boolean): String? {
        val candidates = words(line).filter { w ->
            w.length >= 3 && w.lowercase() !in STOP && !(clean && explicit(w))
        }
        if (candidates.isEmpty()) return null
        val ranked = candidates.distinctBy { it.lowercase() }
            .sortedByDescending { it.length + 3 * ((counts[it.lowercase()] ?: 1) - 1).coerceAtMost(6) }
        return ranked[random.nextInt(minOf(3, ranked.size))]
    }

    private fun clean(line: String): String =
        words(line).fold(line) { acc, w -> if (explicit(w)) acc.replace(w, "*".repeat(w.length)) else acc }

    companion object {
        const val HURL = 1
        const val SLAM = 2
        const val NEON = 3
        const val GLITCH = 4
        const val SPIN = 5
        const val EXPLODE = 6
        const val BACKDROP = 7
        const val ECHO = 8
        const val FLYBY = 9
        const val STYLES = 9

        val MODE_LABELS = listOf("Off", "Words", "Whole lines")
        val RATE_LABELS = listOf("Rare", "Normal", "Often")
        val STYLE_LABELS = listOf("Mixed", "Hurled", "Slam", "Neon sign", "Glitch reveal", "Spin-in", "Explode", "Giant backdrop", "Echo stack", "Fly-by")

        private val WORD = Regex("[\\p{L}][\\p{L}'’]*")
        fun words(line: String): List<String> = WORD.findAll(line).map { it.value.trim('\'', '’') }.filter { it.isNotEmpty() }.toList()

        private val STOP = setOf(
            "the", "and", "you", "your", "you're", "yours", "for", "but", "not", "are", "was", "were", "with", "that",
            "this", "these", "those", "from", "into", "onto", "they", "them", "their", "there", "then", "than", "what",
            "when", "where", "who", "why", "how", "she", "her", "his", "him", "our", "out", "all", "can", "can't", "don't",
            "won't", "i'm", "i've", "i'll", "it's", "its", "just", "got", "get", "gonna", "wanna", "gotta", "yeah", "ooh",
            "oh", "uh", "na", "la", "hey", "have", "has", "had", "been", "will", "would", "could", "should", "about", "some",
            "any", "too", "very", "one", "now", "let", "let's", "like", "said", "say", "says", "did", "does", "doing", "done",
            "ain't", "cause", "'cause", "cos", "till", "until", "over", "under", "off", "own", "only", "also", "each",
        )
        private val EXPLICIT = listOf("fuck", "shit", "bitch", "cunt", "nigg", "dick", "pussy", "cock", "whore", "slut", "asshole", "fag")
        fun explicit(w: String): Boolean = w.lowercase().let { l -> EXPLICIT.any { l.contains(it) } }
    }
}
