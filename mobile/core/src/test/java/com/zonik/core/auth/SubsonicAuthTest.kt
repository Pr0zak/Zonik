package com.zonik.core.auth

import com.zonik.core.model.ServerConfig
import com.zonik.core.util.md5
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SubsonicAuthTest {

    private val legacy = ServerConfig("http://zonik.lan:3000", "zak", "secretkey")
    private val withToken = legacy.copy(deviceToken = "zdt_abc123")

    @Test
    fun legacyKeyUsesSubsonicTokenAuth() {
        val p = SubsonicAuth.params(legacy, "ZonikApp", salt = "salt1234").toMap()
        assertEquals("zak", p["u"])
        assertEquals(md5("secretkeysalt1234"), p["t"])
        assertEquals("salt1234", p["s"])
        assertEquals("1.16.1", p["v"])
        assertEquals("ZonikApp", p["c"])
        assertFalse("apiKey" in p)
        assertFalse("f" in p)
    }

    @Test
    fun deviceTokenSendsApiKeyOnly() {
        val p = SubsonicAuth.params(withToken, "ZonikWear", json = true).toMap()
        assertEquals("zdt_abc123", p["apiKey"])
        assertEquals("1.16.1", p["v"])
        assertEquals("ZonikWear", p["c"])
        assertEquals("json", p["f"])
        for (k in listOf("u", "t", "s", "p")) assertFalse("$k must not be sent with apiKey", k in p)
    }

    @Test
    fun blankTokenFallsBackToKey() {
        val p = SubsonicAuth.params(legacy.copy(deviceToken = "  "), "ZonikApp").toMap()
        assertTrue("u" in p)
        assertFalse("apiKey" in p)
    }

    @Test
    fun appendToPicksSeparator() {
        assertEquals(
            "http://h/rest/ping.view?apiKey=zdt_abc123&v=1.16.1&c=ZonikApp",
            SubsonicAuth.appendTo("http://h/rest/ping.view", withToken, "ZonikApp"),
        )
        assertEquals(
            "http://h/rest/stream.view?id=1&apiKey=zdt_abc123&v=1.16.1&c=ZonikApp",
            SubsonicAuth.appendTo("http://h/rest/stream.view?id=1", withToken, "ZonikApp"),
        )
    }

    @Test
    fun queryIsUrlEncoded() {
        val q = SubsonicAuth.query(legacy.copy(username = "a b&c"), "ZonikApp", salt = "s")
        assertTrue(q, q.startsWith("u=a+b%26c&"))
    }

    @Test
    fun saltIsSixteenAlnum() {
        val s = SubsonicAuth.newSalt()
        assertEquals(16, s.length)
        assertTrue(s.all { it.isLetterOrDigit() })
    }

    @Test
    fun detectsExistingCredentials() {
        assertTrue(SubsonicAuth.hasCredentials(setOf("id", "apiKey")))
        assertTrue(SubsonicAuth.hasCredentials(setOf("u", "t", "s")))
        assertTrue(SubsonicAuth.hasCredentials(setOf("u", "p")))
        assertFalse(SubsonicAuth.hasCredentials(setOf("u")))
        assertFalse(SubsonicAuth.hasCredentials(setOf("id", "size")))
    }
}
