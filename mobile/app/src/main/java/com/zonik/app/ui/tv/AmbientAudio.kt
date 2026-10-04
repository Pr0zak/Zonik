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
    /** How hard the latest onset hit, 0.4..1. Scales the kick it fires. */
    val strength: Float = 1f,
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

    // Rolling peak per band. Divide by this rather than a constant so the visuals answer to the
    // shape of the music rather than to how hot it was mastered; the slow decay lets a genuinely
    // quiet passage read as quiet instead of being normalised straight back up.
    private var lowPeak = MIN_PEAK
    private var midPeak = MIN_PEAK
    private var highPeak = MIN_PEAK

    // Rolling average per band, about a second long. A band is reported as how far it sits
    // above its own recent level, not as a fraction of its peak: a track with a constant bass
    // line otherwise holds `low` near 1 the whole time and the kick has nowhere to go.
    private var lowAvg = 0f
    private var midAvg = 0f
    private var highAvg = 0f

    /** Previous low-band magnitude, for the rising-edge test that flags an onset. */
    private var lastLowRaw = 0f
    private var onsetEnv = 0f
    private var onsetStrength = 0f

    // Recent low-band flux, for an onset threshold that adapts to the track. A fixed threshold
    // fires on every bar of a busy mix and never on a soft one.
    private val fluxHistory = FloatArray(FLUX_HISTORY)
    private var fluxIndex = 0
    private var fluxFilled = 0
    private var capturesSinceOnset = 0

    // Per-band envelope and rolling peak for the 64-band spectrum.
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
        lowAvg += (lowRaw - lowAvg) * AVG_RATE
        midAvg += (midRaw - midAvg) * AVG_RATE
        highAvg += (highRaw - highAvg) * AVG_RATE

        // No envelope here: the renderer eases toward these at frame rate, and smoothing in
        // both places stacked two releases and left every hit smeared across half a second.
        val low = contrast(lowRaw, lowAvg, lowPeak)
        val mid = contrast(midRaw, midAvg, midPeak)
        val high = contrast(highRaw, highAvg, highPeak)

        detectOnset(lowRaw)

        return AmbientPulse(
            low = low, mid = mid, high = high, onset = onsetEnv, strength = onsetStrength,
            spectrum = spectrum(fft, bins, binHz),
        )
    }

    /**
     * An onset is a sharp RISE in low-band energy, not a high level, so a sustained bass note
     * does not fire the drum trigger over and over. The rise has to stand out from the last
     * ~1.5 s of rises (mean plus 1.5 standard deviations), which lets a quiet acoustic track
     * register its kicks and stops a dense electronic one from firing on everything.
     */
    private fun detectOnset(lowRaw: Float) {
        val flux = ((lowRaw - lastLowRaw) / lowPeak).coerceAtLeast(0f)
        lastLowRaw = lowRaw
        capturesSinceOnset++

        var mean = 0f
        var std = 0f
        if (fluxFilled > 0) {
            for (i in 0 until fluxFilled) mean += fluxHistory[i]
            mean /= fluxFilled
            for (i in 0 until fluxFilled) {
                val d = fluxHistory[i] - mean
                std += d * d
            }
            std = sqrt(std / fluxFilled)
        }
        fluxHistory[fluxIndex] = flux
        fluxIndex = (fluxIndex + 1) % FLUX_HISTORY
        if (fluxFilled < FLUX_HISTORY) fluxFilled++

        val threshold = maxOf(mean + ONSET_SIGMA * std, ONSET_MIN_FLUX)
        if (fluxFilled >= FLUX_WARMUP && flux > threshold && capturesSinceOnset >= ONSET_REFRACTORY) {
            onsetEnv = 1f
            // How far over the line it went: a big kick shoves harder than a ghost note.
            onsetStrength = ((flux - threshold) / (2f * std + ONSET_MIN_FLUX) + 0.4f).coerceIn(0.4f, 1f)
            capturesSinceOnset = 0
        } else {
            onsetEnv = (onsetEnv - ONSET_DECAY).coerceAtLeast(0f)
        }
    }

    private fun contrast(raw: Float, avg: Float, peak: Float): Float {
        val floor = avg * CONTRAST_FLOOR
        return ((raw - floor) / (peak - floor).coerceAtLeast(MIN_PEAK)).coerceIn(0f, 1f)
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
        onsetEnv = 0f; onsetStrength = 0f
        lowPeak = MIN_PEAK; midPeak = MIN_PEAK; highPeak = MIN_PEAK
        lowAvg = 0f; midAvg = 0f; highAvg = 0f
        lastLowRaw = 0f
        fluxHistory.fill(0f); fluxIndex = 0; fluxFilled = 0; capturesSinceOnset = 0
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
        const val ONSET_DECAY = 0.12f
        /** ~1 s at the usual 20 Hz capture rate. */
        const val AVG_RATE = 0.05f
        /** How much of the running average counts as "nothing happening". */
        const val CONTRAST_FLOOR = 0.75f
        /** ~1.5 s of captures at 20 Hz. */
        const val FLUX_HISTORY = 30
        const val FLUX_WARMUP = 8
        const val ONSET_SIGMA = 1.5f
        const val ONSET_MIN_FLUX = 0.08f
        /** Captures (50 ms each) before another onset may fire: caps it near 400 BPM. */
        const val ONSET_REFRACTORY = 3
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

    // Onsets in a row that landed well off the grid. A few of those means the grid itself is
    // wrong (a new song section, or the first lock was on an off-beat) and it should re-snap.
    private var offGrid = 0
    private var locked = false

    /** Snap the grid so a beat lands on this moment. */
    fun alignTo(nowMs: Long) {
        phaseOriginMs = nowMs
        locked = true
        offGrid = 0
    }

    /**
     * Feed a detected onset. Snapping to every onset made the grid jump onto each snare and
     * syncopated kick; instead an onset near a predicted beat pulls the grid part of the way
     * toward it, and only a run of onsets that all miss the grid re-snaps it.
     */
    fun onOnset(nowMs: Long) {
        if (!hasTempo) return
        if (!locked) {
            alignTo(nowMs)
            return
        }
        val p = progressAt(nowMs)
        // Signed distance to the nearest beat, as a fraction of a period: + means late.
        val error = if (p < 0.5f) p else p - 1f
        if (kotlin.math.abs(error) < LOCK_WINDOW) {
            phaseOriginMs += (error * periodMs * PULL).toLong()
            offGrid = 0
        } else if (++offGrid >= RESNAP_AFTER) {
            alignTo(nowMs)
        }
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

    private companion object {
        /** An onset within a quarter of a beat of the grid counts as on it. */
        const val LOCK_WINDOW = 0.25f
        /** How far toward an on-grid onset the grid moves. */
        const val PULL = 0.35f
        const val RESNAP_AFTER = 4
    }
}
