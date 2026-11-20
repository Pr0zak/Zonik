package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class JourneyHoopsTest {

    private class Run(val world: JourneyWorld, val clock: BeatClock? = null) {
        val hoops = JourneyHoops()
        val path = JourneyPath()
        var travel = 0.0
        var t = 0L
        /** Every ring once, as where it stands along the flight. */
        val placed = sortedSetOf<Long>()

        fun fly(ms: Long, speed: Float = 1.2f) {
            val end = t + ms
            while (t < end) {
                hoops.update(world, travel, travel % JourneyPath.PERIOD, speed, clock, t, 0.016f, path)
                for (a in hoops.ahead(travel)) placed += Math.round((a + travel) * 1000)
                travel += speed * 0.016
                t += 16
            }
        }
    }

    @Test
    fun `runs of rings come in every world, beyond the fog`() {
        for (e in JOURNEY_WORLDS) {
            val r = Run(JourneyWorld.of(e))
            r.fly(60_000)
            assertTrue("${e.name}: ${r.placed.size} rings", r.placed.size >= 9)
            r.hoops.ahead(r.travel).forEach { assertTrue(it <= r.world.spawn + 6.0) }
        }
    }

    @Test
    fun `each ring stands where the camera is on a beat`() {
        // 120 BPM: a beat every 500 ms; at 1.2 units/s that is a ring every 0.6 units.
        val clock = BeatClock(120f, BeatGrid(120f, 0f, 4, drops = emptyList()))
        clock.syncPosition(0, 0)
        val r = Run(JourneyWorld.of(DemoEffect.CANYON), clock)
        r.fly(60_000)
        assertTrue(r.placed.size >= 9)
        for (z in r.placed) {
            val beats = z / 1000.0 / 1.2 / 0.5
            assertTrue("ring at ${z / 1000.0} is ${beats} beats", abs(beats - Math.round(beats)) < 0.05)
        }
    }

    @Test
    fun `rings in the tunnel worlds fit inside the flight tube`() {
        val r = Run(JourneyWorld.of(DemoEffect.GYROID))
        r.fly(20_000)
        for (i in 0 until JourneyHoops.SLOTS) assertTrue(r.hoops.radiusOf(i) < 0.42f)
    }

    @Test
    fun `runs take every pattern, the tunnel worlds never corkscrew, and a chosen one sticks`() {
        val open = mutableSetOf<Int>()
        val r = Run(JourneyWorld.of(DemoEffect.CANYON))
        repeat(40) { r.fly(10_000); open += r.hoops.pattern }
        assertTrue("open patterns $open", open.containsAll((JourneyHoops.STRAIGHT..JourneyHoops.CURVE).toList()))
        val g = Run(JourneyWorld.of(DemoEffect.GYROID))
        repeat(40) {
            g.fly(10_000)
            assertTrue(g.hoops.pattern != JourneyHoops.CORKSCREW && g.hoops.pattern != JourneyHoops.CURVE)
        }
        val c = Run(JourneyWorld.of(DemoEffect.CANYON))
        c.hoops.forced = JourneyHoops.CORKSCREW
        repeat(10) { c.fly(10_000); org.junit.Assert.assertEquals(JourneyHoops.CORKSCREW, c.hoops.pattern) }
    }
}

class JourneyOptionsTest {
    @Test
    fun `options survive a round trip and fall back field by field`() {
        val o = JourneyOptions(length = 2, speed = 0, rings = false, fish = true, shuffle = false, ringPattern = 3, style = 2,
            camera = false, drops = false, weather = false, boards = false, mirror = false, kickFx = true)
        org.junit.Assert.assertEquals(o, JourneyOptions.decode(o.encode()))
        org.junit.Assert.assertEquals(JourneyOptions(), JourneyOptions.decode(null))
        org.junit.Assert.assertEquals(JourneyOptions(length = 0), JourneyOptions.decode("0,9"))
        // An older app's seven fields keep the new options at their defaults.
        org.junit.Assert.assertEquals(JourneyOptions(), JourneyOptions.decode("1,1,1,1,1,0,0"))
    }

    @Test
    fun `a fixed order keeps the worlds as listed`() {
        val ws = JOURNEY_WORLDS.take(5)
        org.junit.Assert.assertEquals(ws, JourneySequencer.ordered(ws, JourneySequencer.FIXED_ORDER))
    }

    @Test
    fun `a chosen style always comes up, a mix is mostly as made`() {
        val r = kotlin.random.Random(4)
        org.junit.Assert.assertEquals(2, JourneyOptions(style = 3).pickStyle(r))
        val picks = List(1000) { JourneyOptions().pickStyle(r) }
        assertTrue(picks.count { it == 0 } in 520..680)
        assertTrue(picks.toSet() == setOf(0, 1, 2))
    }
}

class JourneyRollTest {
    @Test
    fun `rolls come now and then and always end level`() {
        val roll = JourneyRoll()
        var rolls = 0
        var was = false
        var biggest = 0f
        for (i in 0 until 60 * 600) {
            roll.update(1f / 60f, null, i * 16L)
            biggest = maxOf(biggest, kotlin.math.abs(roll.value))
            if (was && !roll.rolling) assertEquals(0f, roll.value, 1e-6f)
            if (roll.rolling && !was) rolls++
            was = roll.rolling
        }
        assertTrue("$rolls rolls in ten minutes", rolls in 15..60)
        assertTrue(biggest > 6f) // a full turn came up
    }
}
