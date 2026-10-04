package com.zonik.app.ui.tv

import com.zonik.app.data.api.TvEffectReport

/**
 * How each visualizer effect has run since the last report to the server: time on screen,
 * frames drawn (so the server can work out the frame rate), kicks and showings.
 *
 * Written by the renderer on the GL thread every frame and drained by the view model every
 * few minutes, so everything goes through one lock. The work per frame is a map lookup and
 * three additions.
 */
object TvEffectStats {
    private class Totals {
        var seconds = 0f
        var frames = 0
        var kicks = 0
        var shows = 0
    }

    private val totals = HashMap<String, Totals>()

    private fun of(effect: DemoEffect) = totals.getOrPut(effect.name) { Totals() }

    /** One frame of [effect] alone on screen (not mid-transition), [dt] seconds long. */
    @Synchronized
    fun frame(effect: DemoEffect, dt: Float) {
        val t = of(effect)
        t.seconds += dt
        t.frames++
    }

    @Synchronized
    fun kick(effect: DemoEffect) {
        of(effect).kicks++
    }

    @Synchronized
    fun shown(effect: DemoEffect) {
        of(effect).shows++
    }

    /** Everything collected since the last drain, emptied. */
    @Synchronized
    fun drain(): List<TvEffectReport> {
        val out = totals.map { (name, t) -> TvEffectReport(name, t.seconds, t.frames, t.kicks, t.shows) }
        totals.clear()
        return out
    }

    /** Puts a report back after a failed upload, so the numbers go up with the next one. */
    @Synchronized
    fun restore(reports: List<TvEffectReport>) {
        for (r in reports) {
            val t = totals.getOrPut(r.effect) { Totals() }
            t.seconds += r.seconds
            t.frames += r.frames
            t.kicks += r.kicks
            t.shows += r.shows
        }
    }
}
