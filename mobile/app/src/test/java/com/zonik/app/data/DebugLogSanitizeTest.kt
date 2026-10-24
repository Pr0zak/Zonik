package com.zonik.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class DebugLogSanitizeTest {

    @Test
    fun masksDeviceTokenQueryParam() {
        val s = DebugLog.sanitizeUrl("GET http://h:3000/rest/stream.view?id=1&apiKey=zdt_secret&v=1.16.1&c=ZonikApp")
        assertEquals("GET http://h:3000/rest/stream.view?id=1&apiKey=***&v=1.16.1&c=ZonikApp", s)
    }

    @Test
    fun masksLegacyTokenAuth() {
        val s = DebugLog.sanitizeUrl("http://h/rest/ping.view?u=zak&t=abcdef&s=salt&v=1.16.1")
        assertEquals("http://h/rest/ping.view?u=***&t=***&s=***&v=1.16.1", s)
    }

    @Test
    fun masksJsonSecretsAndBearer() {
        val s = DebugLog.sanitizeUrl(
            """{"status":"ready","username":"zak","api_key":"k123","device_token":"zdt_x"} Authorization: Bearer zdt_y"""
        )
        assertFalse(s, s.contains("k123"))
        assertFalse(s, s.contains("zdt_x"))
        assertFalse(s, s.contains("zdt_y"))
    }

    @Test
    fun leavesOrdinaryTextAlone() {
        val text = "Found Zonik at http://10.0.0.205:3000 via MDNS"
        assertEquals(text, DebugLog.sanitizeUrl(text))
    }
}
