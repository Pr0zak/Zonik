package com.zonik.core.auth

/**
 * Turns what someone types into the "server" box into a URL. Pure Kotlin, unit-tested.
 *
 * - blank → null
 * - full URL (`http://…`, `https://…`) → unchanged (trailing `/` trimmed)
 * - `zonik` → `http://zonik.lan:3000`
 * - `205` or `.205` → the device's own /24 (from its Wi-Fi IPv4) with `:3000`; null when the
 *   device address is unknown or the number is not an octet
 * - a bare host or IP, optionally with `:port` and a path → `http://` added, and `:3000` when
 *   there is no port
 */
object ServerUrlNormalizer {

    const val DEFAULT_PORT = 3000
    const val DEFAULT_HOST = "zonik.lan"

    private val octetOnly = Regex("""^\.?(\d{1,3})$""")
    private val ipv4 = Regex("""^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$""")

    fun normalize(input: String?, deviceIpv4: String? = null): String? {
        val raw = input?.trim()?.trimEnd('/') ?: return null
        if (raw.isEmpty()) return null

        val lower = raw.lowercase()
        if (lower.startsWith("http://") || lower.startsWith("https://")) {
            val rest = raw.substringAfter("://")
            return if (rest.isBlank()) null else raw
        }
        if (raw.contains("://")) return null // some other scheme
        if (raw.any { it.isWhitespace() }) return null

        if (lower == "zonik") return "http://$DEFAULT_HOST:$DEFAULT_PORT"

        octetOnly.matchEntire(raw)?.let { m ->
            val octet = m.groupValues[1].toInt()
            if (octet > 255) return null
            val prefix = subnetPrefix(deviceIpv4) ?: return null
            return "http://$prefix.$octet:$DEFAULT_PORT"
        }

        // host[:port][/path]
        val slash = raw.indexOf('/')
        val authority = if (slash >= 0) raw.substring(0, slash) else raw
        val path = if (slash >= 0) raw.substring(slash) else ""
        if (authority.isEmpty()) return null

        val hasPort = if (authority.startsWith("[")) {
            // IPv6 literal: [::1] or [::1]:3000
            val close = authority.indexOf(']')
            if (close < 0) return null
            authority.length > close + 1 && authority[close + 1] == ':'
        } else {
            val colon = authority.lastIndexOf(':')
            if (colon >= 0) {
                val port = authority.substring(colon + 1)
                if (port.isEmpty() || port.any { !it.isDigit() } || port.toInt() !in 1..65535) return null
                if (colon == 0) return null
                true
            } else false
        }
        val host = if (hasPort) authority else "$authority:$DEFAULT_PORT"
        return "http://$host$path"
    }

    /** "10.0.0.12" → "10.0.0"; null for anything that is not a dotted IPv4. */
    fun subnetPrefix(ipv4Address: String?): String? {
        val m = ipv4.matchEntire(ipv4Address?.trim() ?: return null) ?: return null
        val parts = m.groupValues.drop(1).map { it.toInt() }
        if (parts.any { it > 255 }) return null
        return parts.take(3).joinToString(".")
    }

    /** "10.0.0.205" with mask /24 → "10.0.0.255" (for the UDP probe's subnet broadcast). */
    fun broadcastFor24(ipv4Address: String?): String? = subnetPrefix(ipv4Address)?.let { "$it.255" }

    /** Host part of a URL for display: "http://10.0.0.205:3000" → "10.0.0.205". */
    fun displayHost(url: String): String =
        url.substringAfter("://").substringBefore('/').let { authority ->
            if (authority.startsWith("[")) authority.substringBefore(']') + "]"
            else authority.substringBefore(':')
        }
}
