package com.zonik.app.ui.tv

import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.random.Random

/**
 * A Misiurewicz point: a c on the edge of the Mandelbrot set whose orbit from 0 settles, after
 * [preperiod] steps, onto a repelling cycle of length [period].
 *
 * Two properties make these the right places to dive into. The set around one is asymptotically
 * self-similar — zoom in by |[lambda]| and turn by arg([lambda]) and the picture repeats — so a
 * dive can loop forever at constant cost. And the orbit of c itself is known exactly forever
 * (the preperiod, then the [cycle] over and over), which is the reference orbit perturbation
 * needs to render at any depth in fp32.
 */
class MandelTarget(
    val cRe: Double,
    val cIm: Double,
    val preperiod: Int,
    val period: Int,
    /** The cycle's points, re/im interleaved, [period] of them. */
    val cycle: FloatArray,
    /** |λ|: how much deeper one turn of the self-similar loop goes. */
    val lambdaMag: Double,
    /** arg(λ): how far the picture turns over one loop. */
    val lambdaArg: Double,
)

object MandelbrotTargets {

    private const val MAX_PERIOD = 3
    private const val MAX_PREPERIOD = 6

    /**
     * A random Misiurewicz point, found by Newton's method from a random start. Rejects points
     * on the real axis (a line, and dull), and loops that zoom too slowly (every step of the
     * loop would cost more iterations) or too fast (the repeat would be visible as a lurch).
     */
    fun random(rng: Random = Random.Default): MandelTarget {
        repeat(400) {
            val pre = rng.nextInt(2, MAX_PREPERIOD + 1)
            val per = rng.nextInt(1, MAX_PERIOD + 1)
            val found = solve(
                rng.nextDouble(-2.0, 0.5), rng.nextDouble(-1.2, 1.2), pre, per
            ) ?: return@repeat
            val (re, im) = found
            if (kotlin.math.abs(im) < 1e-3) return@repeat
            val target = validate(re, im, pre, per) ?: return@repeat
            if (target.lambdaMag in 2.2..40.0) return target
        }
        // Newton failed 400 times running, which it should not; the seahorse-valley spiral is
        // a known-good Misiurewicz point (preperiod 4, period 1) to fall back on.
        return validate(-0.77568377, 0.13646737, 4, 1)!!
    }

    /** Newton on g(c) = f^(pre+per)(0) − f^pre(0). */
    private fun solve(startRe: Double, startIm: Double, pre: Int, per: Int): Pair<Double, Double>? {
        var cr = startRe
        var ci = startIm
        repeat(60) {
            var zr = 0.0; var zi = 0.0
            var dr = 0.0; var di = 0.0
            var aR = 0.0; var aI = 0.0; var daR = 0.0; var daI = 0.0
            for (n in 1..pre + per) {
                // dz' = 2 z dz + 1, then z' = z² + c
                val ndr = 2 * (zr * dr - zi * di) + 1
                val ndi = 2 * (zr * di + zi * dr)
                val nzr = zr * zr - zi * zi + cr
                val nzi = 2 * zr * zi + ci
                zr = nzr; zi = nzi; dr = ndr; di = ndi
                if (zr * zr + zi * zi > 1e6) return null
                if (n == pre) { aR = zr; aI = zi; daR = dr; daI = di }
            }
            val gR = zr - aR; val gI = zi - aI
            val gdR = dr - daR; val gdI = di - daI
            val den = gdR * gdR + gdI * gdI
            if (den < 1e-300) return null
            val stepR = (gR * gdR + gI * gdI) / den
            val stepI = (gI * gdR - gR * gdI) / den
            cr -= stepR; ci -= stepI
            if (hypot(stepR, stepI) < 1e-14) return cr to ci
        }
        return null
    }

    /**
     * Checks that c really has exactly this preperiod and period (Newton happily lands on a
     * point with a shorter one) and works out the cycle and its multiplier.
     */
    private fun validate(cr: Double, ci: Double, pre: Int, per: Int): MandelTarget? {
        if (hypot(cr, ci) > 2.0) return null
        val zr = DoubleArray(pre + per + 1)
        val zi = DoubleArray(pre + per + 1)
        for (n in 1..pre + per) {
            zr[n] = zr[n - 1] * zr[n - 1] - zi[n - 1] * zi[n - 1] + cr
            zi[n] = 2 * zr[n - 1] * zi[n - 1] + ci
        }
        fun dist(a: Int, b: Int) = hypot(zr[a] - zr[b], zi[a] - zi[b])
        if (dist(pre + per, pre) > 1e-9) return null
        // Exact preperiod: the orbit must not already be on the cycle one step earlier.
        if (dist(pre - 1 + per, pre - 1) < 1e-6) return null
        // Exact period: no shorter cycle.
        for (q in 1 until per) if (per % q == 0 && dist(pre + q, pre) < 1e-6) return null

        // λ = ∏ 2·z over the cycle.
        var lr = 1.0; var li = 0.0
        val cycle = FloatArray(per * 2)
        for (j in 0 until per) {
            val r = zr[pre + j]; val i = zi[pre + j]
            cycle[j * 2] = r.toFloat(); cycle[j * 2 + 1] = i.toFloat()
            val nr = lr * 2 * r - li * 2 * i
            val ni = lr * 2 * i + li * 2 * r
            lr = nr; li = ni
        }
        return MandelTarget(cr, ci, pre, per, cycle, hypot(lr, li), atan2(li, lr))
    }
}
