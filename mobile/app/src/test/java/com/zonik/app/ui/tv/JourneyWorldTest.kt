package com.zonik.app.ui.tv

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class JourneyWorldTest {

    @Test
    fun `every world's cells fit the 6π wrap exactly`() {
        for (e in JOURNEY_WORLDS) {
            val w = JourneyWorld.of(e)
            // The camera's cell index is taken modulo the count, so cell × count must be 6π
            // (or divide it), or the world jumps when uPhase wraps.
            val perWrap = 6.0 * Math.PI / w.cell
            assertEquals("${e.name} cells per wrap", Math.round(perWrap).toDouble(), perWrap, 1e-9)
            assertEquals("${e.name} count", 0.0, perWrap % w.cells, 1e-9)
        }
    }

    @Test
    fun `open worlds have landmarks past their fog, enclosed ones none`() {
        val open = setOf(DemoEffect.SKY, DemoEffect.CANYON, DemoEffect.SEASTACKS, DemoEffect.NIGHTCITY,
            DemoEffect.STATION, DemoEffect.ASTEROIDS, DemoEffect.CAVES, DemoEffect.ABYSS)
        for (e in JOURNEY_WORLDS) {
            val w = JourneyWorld.of(e)
            assertEquals(e.name, e in open, w.large.isNotEmpty())
            assertTrue(e.name, w.spawn >= 6.0)
        }
        assertEquals(12, JOURNEY_WORLDS.size)
    }
}
