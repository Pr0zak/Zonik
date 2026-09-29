package com.zonik.app.ui.tv

import kotlin.math.sqrt

/**
 * What the visuals get to react to, once per capture.
 *
 * Three bands rather than one scalar, because a single "loudness" number produces a haze that
 * brightens and dims — smooth, and smooth is invisible from three metres. Separating the kick
 * from the cymbals is what lets different elements of the scene answer to different parts of
 * the music.
 */
data class AmbientPulse(
    /** ~40-160 Hz. The kick. */
    val low: Float = 0f,
    /** ~300-2000 Hz. Body: vocals, guitars, snare. */
    val mid: Float = 0f,
    /** ~4-12 kHz. Air: cymbals, hats, sibilance. */
    val high: Float = 0f,
    /** Rises on a detected onset and decays; a discrete event rather than a level. */
    val onset: Float = 0f,
    /**
     * [SPECTRUM_BANDS] log-spaced bands from 40 Hz to 16 kHz, each 0..1, for effects that draw
     * the spectrum itself. Null when there is no capture.
     */
    val spectrum: FloatArray? = null,
    /** [WAVEFORM_POINTS] samples of the output waveform, 0..1 with 0.5 as silence. */
    val waveform: FloatArray? = null,
)

const val WAVEFORM_POINTS = 256

const val SPECTRUM_BANDS = 64

/**
 * Turns raw FFT frames into an [AmbientPulse].
 *
 * Two things the old implementation got wrong and this fixes. It captured 128 points, which at
 * a 44.1 kHz sample rate is a 344 Hz bin — so the bins it called "bass" actually spanned roughly
 * 345-1723 Hz, which is vocals and guitars, and the kick's fundamental fell in the one bin it
 * skipped. And it divided by fixed constants, so a quietly-mastered record barely moved the
 * visuals while a loud one pinned them.
 *
 * Everything here runs on the audio capture thread, once per frame, over a few hundred floats.
 */
class PulseAnalyzer(private val sampleRate: Int) {

    private var lowEnv = 0f
    private var midEnv = 0f
    private var highEnv = 0f
    private var onsetEnv = 0f

    // Rolling peak per band. Divide by this rather than a constant so the visuals answer to the
    // shape of the music rather than to how hot it was mastered; the slow decay lets a genuinely
    // quiet passage read as quiet instead of being normalised straight back up.
    private var lowPeak = MIN_PEAK
    private var midPeak = MIN_PEAK
    private var highPeak = MIN_PEAK

    /** Previous low-band magnitude, for the rising-edge test that flags an onset. */
    private var lastLowRaw = 0f

    // Per-band envelope and rolling peak, like the three bands above but 64 of them.
    private val bandEnv = FloatArray(SPECTRUM_BANDS)
    private val bandPeak = FloatArray(SPECTRUM_BANDS) { MIN_PEAK }

    fun process(fft: ByteArray): AmbientPulse {
        val bins = fft.size / 2
        if (bins < 4) return AmbientPulse()
        val binHz = sampleRate.toFloat() / (bins * 2)

        val lowRaw = magnitudeBetween(fft, bins, binHz, 40f, 160f)
        val midRaw = magnitudeBetween(fft, bins, binHz, 300f, 2000f)
        val highRaw = magnitudeBetween(fft, bins, binHz, 4000f, 12000f)

        lowPeak = decayPeak(lowPeak, lowRaw)
        midPeak = decayPeak(midPeak, midRaw)
        highPeak = decayPeak(highPeak, highRaw)

        // Asymmetric: snap up on a hit, ease down after it. A symmetric filter either lags the
        // attack or flickers on the release, and the attack is the part you actually see.
        lowEnv = follow(lowEnv, (lowRaw / lowPeak).coerceIn(0f, 1f))
        midEnv = follow(midEnv, (midRaw / midPeak).coerceIn(0f, 1f))
        highEnv = follow(highEnv, (highRaw / highPeak).coerceIn(0f, 1f))

        // An onset is a sharp RISE in low-band energy, not a high level — a sustained bass note
        // must not fire the drum trigger over and over.
        val rise = (lowRaw - lastLowRaw) / lowPeak
        lastLowRaw = lowRaw
        onsetEnv = if (rise > ONSET_THRESHOLD) 1f else (onsetEnv - ONSET_DECAY).coerceAtLeast(0f)

        return AmbientPulse(
            low = lowEnv, mid = midEnv, high = highEnv, onset = onsetEnv,
            spectrum = spectrum(fft, bins, binHz),
        )
    }

    /**
     * Log-spaced bands, so the bass gets as many bars as the treble does rather than the four
     * bins a linear split would give it. Each band has its own rolling peak for the same reason
     * the three main bands do: hi-hats are quiet in absolute terms and would never move a bar
     * normalised against the kick.
     */
    private fun spectrum(fft: ByteArray, bins: Int, binHz: Float): FloatArray {
        val out = FloatArray(SPECTRUM_BANDS)
        for (i in 0 until SPECTRUM_BANDS) {
            val from = SPECTRUM_LOW_HZ * Math.pow(SPECTRUM_RATIO, i / SPECTRUM_BANDS.toDouble()).toFloat()
            val to = SPECTRUM_LOW_HZ * Math.pow(SPECTRUM_RATIO, (i + 1) / SPECTRUM_BANDS.toDouble()).toFloat()
            // A low band narrower than one bin still gets the bin it falls in.
            val first = (from / binHz).toInt().coerceIn(1, bins - 1)
            val last = maxOf(first, (to / binHz).toInt().coerceAtMost(bins - 1))
            var sum = 0f
            for (b in first..last) {
                val re = fft[2 * b].toFloat()
                val im = if (2 * b + 1 < fft.size) fft[2 * b + 1].toFloat() else 0f
                sum += sqrt(re * re + im * im)
            }
            val raw = sum / (last - first + 1)
            bandPeak[i] = decayPeak(bandPeak[i], raw)
            bandEnv[i] = follow(bandEnv[i], (raw / bandPeak[i]).coerceIn(0f, 1f))
            out[i] = bandEnv[i]
        }
        return out
    }

    fun reset() {
        lowEnv = 0f; midEnv = 0f; highEnv = 0f; onsetEnv = 0f
        lowPeak = MIN_PEAK; midPeak = MIN_PEAK; highPeak = MIN_PEAK
        lastLowRaw = 0f
        bandEnv.fill(0f)
        bandPeak.fill(MIN_PEAK)
    }

    private fun magnitudeBetween(
        fft: ByteArray, bins: Int, binHz: Float, fromHz: Float, toHz: Float
    ): Float {
        val first = (fromHz / binHz).toInt().coerceAtLeast(1)
        val last = (toHz / binHz).toInt().coerceAtMost(bins - 1)
        if (last < first) return 0f
        var sum = 0f
        for (i in first..last) {
            val re = fft[2 * i].toFloat()
            val im = if (2 * i + 1 < fft.size) fft[2 * i + 1].toFloat() else 0f
            sum += sqrt(re * re + im * im)
        }
        return sum / (last - first + 1)
    }

    private fun decayPeak(peak: Float, value: Float): Float =
        if (value > peak) value else (peak * PEAK_DECAY).coerceAtLeast(MIN_PEAK)

    private fun follow(env: Float, target: Float): Float =
        env + (target - env) * (if (target > env) ATTACK else RELEASE)

    private companion object {
        const val ATTACK = 0.8f
        const val RELEASE = 0.13f
        const val PEAK_DECAY = 0.995f
        const val MIN_PEAK = 1e-3f
        const val ONSET_THRESHOLD = 0.22f
        const val ONSET_DECAY = 0.12f
        const val SPECTRUM_LOW_HZ = 40f
        /** 40 Hz × 400 = 16 kHz at the top of the last band. */
        const val SPECTRUM_RATIO = 400.0
    }
}

/**
 * A beat clock driven by the server's stored tempo.
 *
 * The server has a BPM for almost every track but no downbeat position, so the grid knows how
 * far apart the beats are and not where they start. Phase comes from the audio: an onset nudges
 * the clock into alignment. Once locked, the grid does the one thing listening cannot — it knows
 * when the NEXT beat lands, so motion can start early and peak exactly on it instead of always
 * beginning after the moment it is meant to mark.
 */
class BeatClock(bpm: Float) {
    private val periodMs: Float = if (bpm > 20f) 60_000f / bpm else 0f
    // Written on the main thread when an onset lands, read every frame on the GL thread.
    @Volatile private var phaseOriginMs: Long = 0L

    val hasTempo: Boolean get() = periodMs > 0f

    /** Snap the grid so a beat lands on this moment. */
    fun alignTo(nowMs: Long) {
        phaseOriginMs = nowMs
    }

    /**
     * 0 at the instant of a beat, rising towards 1 just before the next one.
     */
    fun progressAt(nowMs: Long): Float {
        if (!hasTempo) return 0f
        val since = (nowMs - phaseOriginMs).toFloat()
        val p = (since % periodMs) / periodMs
        return if (p < 0f) p + 1f else p
    }

    /** Milliseconds until the next beat, for anticipation. */
    fun msToNextBeat(nowMs: Long): Float =
        if (!hasTempo) Float.MAX_VALUE else periodMs * (1f - progressAt(nowMs))

    /**
     * Motion that PEAKS on the beat rather than starting there: swells over the last
     * [leadMs] before the grid's next beat, then resets.
     */
    fun anticipation(nowMs: Long, leadMs: Float = 140f): Float {
        if (!hasTempo) return 0f
        val toNext = msToNextBeat(nowMs)
        if (toNext > leadMs) return 0f
        return 1f - (toNext / leadMs)
    }
}
