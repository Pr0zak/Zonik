package com.zonik.core.auth

import com.zonik.core.model.ServerConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthModelsTest {

    private fun poll(json: String) = AuthJson.json.decodeFromString(PairPollResponse.serializer(), json)

    @Test fun pendingAndExpired() {
        val p = poll("""{"status":"pending"}""")
        assertFalse(p.isReady); assertNull(p.toServerConfig("http://x"))
        assertTrue(poll("""{"status":"expired"}""").isExpired)
    }

    @Test fun readyV2CarriesDeviceToken() {
        val p = poll(
            """{"status":"ready","url":"http://10.0.0.205:3000/","username":"zak","api_key":"k1",
               "device_token":"zdt_t1","display_name":"Zak","extra":1}"""
        )
        assertEquals("Zak", p.displayName)
        assertEquals(
            ServerConfig("http://10.0.0.205:3000", "zak", "k1", "zdt_t1"),
            p.toServerConfig("http://fallback:3000"),
        )
    }

    @Test fun readyLegacyHasKeyOnly() {
        val c = poll("""{"status":"ready","url":"http://h:3000","username":"zak","api_key":"k1"}""").toServerConfig()!!
        assertEquals("k1", c.apiKey)
        assertNull(c.deviceToken)
        assertFalse(c.hasDeviceToken)
    }

    @Test fun readyWithoutUrlUsesFallback() {
        val c = poll("""{"status":"ready","username":"zak","device_token":"zdt_t1"}""").toServerConfig("http://zonik.lan:3000")!!
        assertEquals("http://zonik.lan:3000", c.url)
        assertEquals("", c.apiKey)
        assertEquals("zdt_t1", c.deviceToken)
    }

    @Test fun readyWithoutCredentialsIsRejected() {
        assertNull(poll("""{"status":"ready","url":"http://h","username":"zak"}""").toServerConfig())
        assertNull(poll("""{"status":"ready","url":"http://h","api_key":"k"}""").toServerConfig())
    }

    @Test fun deviceLoginResponse() {
        val r = AuthJson.json.decodeFromString(
            DeviceLoginResponse.serializer(),
            """{"token":"zdt_x","user":{"id":"u1","username":"zak","display_name":null,"role":"admin",
               "is_admin":true,"permissions":["x"],"must_change_password":false,"auth_method":"device"}}"""
        )
        assertEquals("zdt_x", r.token)
        assertEquals("zak", r.user.shownName)
        assertEquals("admin", r.user.role)
    }

    @Test fun devicesList() {
        val items = AuthJson.json.decodeFromString(
            kotlinx.serialization.builtins.ListSerializer(DeviceItem.serializer()),
            """[{"id":"s1","kind":"session","label":"Chrome","platform":"web","ip":"1.2.3.4","current":false},
                {"id":"d1","kind":"device","label":"Pixel","platform":"android","ip":null,"current":true}]"""
        )
        assertEquals("d1", items.single { it.current }.id)
    }

    @Test fun pairInfo() {
        val i = AuthJson.json.decodeFromString(
            PairInfo.serializer(),
            """{"status":"pending","label":"Shield TV","platform":"tv","created_at":"2026-10-24T10:00:00Z","expires":"x"}"""
        )
        assertTrue(i.isPending)
        assertEquals("Shield TV", i.label)
    }

    @Test fun probeReply() {
        val s = AuthJson.parseProbeReply("""{"zonik":1,"name":"Zonik","version":"0.48.0","url":"http://10.0.0.205:3000/"}""")!!
        assertEquals("http://10.0.0.205:3000", s.url)
        assertEquals("10.0.0.205", s.host)
        assertEquals(DiscoveredServer.Source.UDP, s.source)
        assertNull(AuthJson.parseProbeReply("""{"zonik":2,"url":"http://x"}"""))
        assertNull(AuthJson.parseProbeReply("""{"zonik":1}"""))
        assertNull(AuthJson.parseProbeReply("garbage"))
    }

    @Test fun errorDetail() {
        assertEquals("Invalid username or password", AuthJson.errorDetail("""{"detail":"Invalid username or password"}"""))
        assertEquals("field required", AuthJson.errorDetail("""{"detail":[{"loc":["body"],"msg":"field required"}]}"""))
        assertNull(AuthJson.errorDetail("<html>"))
        assertNull(AuthJson.errorDetail(null))
    }

    @Test fun configToStringHidesSecrets() {
        val s = ServerConfig("http://h", "zak", "k1", "zdt_t").toString()
        assertFalse(s.contains("k1")); assertFalse(s.contains("zdt_t"))
    }
}
