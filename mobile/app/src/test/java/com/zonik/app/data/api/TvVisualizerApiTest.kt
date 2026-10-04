package com.zonik.app.data.api

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

class TvVisualizerApiTest {
    // Mirrors AppModule's Json: unknown keys ignored, defaults (here, nulls) not encoded.
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun `a partial update sends only the changed setting`() {
        val body = TvVisualizerConfigUpdate(TvVisualizerConfig(rotateSec = 30), updatedBy = "TV")
        assertEquals("""{"config":{"rotate_sec":30},"updated_by":"TV"}""", json.encodeToString(body))
    }

    @Test
    fun `the server's response parses, extra keys and all`() {
        val raw = """{"config":{"enabled":true,"delay_sec":10,"effects_off":["MARBLE"],"rotate_sec":45,
            "info":"FADE","transition":-1,"transition_ms":1600,"colors":"ALBUM","trails":false,"beat_reactive":true},
            "defaults":{},"options":{"x":[[1,"a"]]},"updated_at":null,"updated_by":null}"""
        val r = json.decodeFromString<TvVisualizerConfigResponse>(raw)
        assertEquals(listOf("MARBLE"), r.config.effectsOff)
        assertEquals(45, r.config.rotateSec)
        assertEquals(null, r.updatedAt)
    }
}
