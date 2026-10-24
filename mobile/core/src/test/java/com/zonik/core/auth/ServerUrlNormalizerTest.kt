package com.zonik.core.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerUrlNormalizerTest {

    private fun n(s: String?, ip: String? = "10.0.0.37") = ServerUrlNormalizer.normalize(s, ip)

    @Test fun blankIsNull() {
        assertNull(n(null)); assertNull(n("")); assertNull(n("   "))
    }

    @Test fun zonikShorthand() {
        assertEquals("http://zonik.lan:3000", n("zonik"))
        assertEquals("http://zonik.lan:3000", n(" Zonik "))
    }

    @Test fun lastOctetUsesDeviceSubnet() {
        assertEquals("http://10.0.0.205:3000", n("205"))
        assertEquals("http://10.0.0.205:3000", n(".205"))
        assertEquals("http://192.168.1.5:3000", n("5", "192.168.1.77"))
    }

    @Test fun lastOctetNeedsDeviceIp() {
        assertNull(n("205", null))
        assertNull(n("205", "not-an-ip"))
        assertNull(n("300"))
    }

    @Test fun bareHostGetsSchemeAndPort() {
        assertEquals("http://zonik.lan:3000", n("zonik.lan"))
        assertEquals("http://10.0.0.205:3000", n("10.0.0.205"))
        assertEquals("http://music.example.com:3000", n("music.example.com/"))
    }

    @Test fun bareHostKeepsPortAndPath() {
        assertEquals("http://10.0.0.205:8080", n("10.0.0.205:8080"))
        assertEquals("http://myhost:3000/zonik", n("myhost/zonik"))
        assertEquals("http://myhost:443/zonik", n("myhost:443/zonik"))
        assertEquals("http://[::1]:3000", n("[::1]"))
        assertEquals("http://[::1]:4000", n("[::1]:4000"))
    }

    @Test fun fullUrlsUnchanged() {
        assertEquals("https://music.example.com", n("https://music.example.com/"))
        assertEquals("http://10.0.0.205:3000", n("http://10.0.0.205:3000"))
        assertEquals("HTTPS://Zonik.example", n("HTTPS://Zonik.example"))
        assertEquals("https://example.com/sub", n("https://example.com/sub"))
    }

    @Test fun rejectsJunk() {
        assertNull(n("ftp://x"))
        assertNull(n("http://"))
        assertNull(n("my host"))
        assertNull(n("host:abc"))
        assertNull(n("host:99999"))
        assertNull(n(":3000"))
    }

    @Test fun helpers() {
        assertEquals("10.0.0", ServerUrlNormalizer.subnetPrefix("10.0.0.37"))
        assertNull(ServerUrlNormalizer.subnetPrefix("10.0.0"))
        assertEquals("10.0.0.255", ServerUrlNormalizer.broadcastFor24("10.0.0.37"))
        assertEquals("10.0.0.205", ServerUrlNormalizer.displayHost("http://10.0.0.205:3000"))
        assertEquals("zonik.lan", ServerUrlNormalizer.displayHost("https://zonik.lan/x"))
    }
}
