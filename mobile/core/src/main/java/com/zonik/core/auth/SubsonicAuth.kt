package com.zonik.core.auth

import com.zonik.core.model.ServerConfig
import com.zonik.core.util.md5
import java.net.URLEncoder
import kotlin.random.Random

/**
 * The one place that turns a [ServerConfig] into request credentials. Every URL the apps build
 * (streams, cover art, waveforms, the WebSocket, the interceptor for Retrofit calls) goes
 * through here, so switching a login from the legacy API key to a device token changes all of
 * them at once.
 *
 * - Device token present: OpenSubsonic `apiKey=<token>`. `u`/`t`/`s`/`p` are NOT sent — an
 *   OpenSubsonic server rejects a request carrying both (error 43).
 * - Otherwise: classic Subsonic token auth, `u` + `t = md5(apiKey + salt)` + `s`.
 *
 * `v` and `c` are always sent; `f=json` when asked.
 */
object SubsonicAuth {

    const val API_VERSION = "1.16.1"

    /** Query parameter names that carry credentials (for "already signed?" checks). */
    val CREDENTIAL_PARAMS: Set<String> = setOf("apiKey", "u", "t", "s", "p")

    private const val SALT_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

    fun newSalt(random: Random = Random.Default): String =
        (1..16).map { SALT_CHARS[random.nextInt(SALT_CHARS.length)] }.joinToString("")

    /** Ordered (name, value) pairs, unencoded. [salt] is only for tests. */
    fun params(
        config: ServerConfig,
        clientName: String,
        json: Boolean = false,
        salt: String? = null,
    ): List<Pair<String, String>> {
        val out = ArrayList<Pair<String, String>>(6)
        val token = config.deviceToken?.takeIf { it.isNotBlank() }
        if (token != null) {
            out += "apiKey" to token
        } else {
            val s = salt ?: newSalt()
            out += "u" to config.username
            out += "t" to md5(config.apiKey + s)
            out += "s" to s
        }
        out += "v" to API_VERSION
        out += "c" to clientName
        if (json) out += "f" to "json"
        return out
    }

    /** `a=1&b=2`, URL-encoded, no leading separator. */
    fun query(
        config: ServerConfig,
        clientName: String,
        json: Boolean = false,
        salt: String? = null,
    ): String = params(config, clientName, json, salt).joinToString("&") { (k, v) -> "${enc(k)}=${enc(v)}" }

    /** [url] with the auth params appended, choosing `?` or `&` as needed. */
    fun appendTo(
        url: String,
        config: ServerConfig,
        clientName: String,
        json: Boolean = false,
        salt: String? = null,
    ): String {
        val q = query(config, clientName, json, salt)
        val sep = when {
            !url.contains('?') -> "?"
            url.endsWith("?") || url.endsWith("&") -> ""
            else -> "&"
        }
        return url + sep + q
    }

    /** True when a request with these query parameter names already carries credentials. */
    fun hasCredentials(paramNames: Collection<String>): Boolean =
        "apiKey" in paramNames || ("u" in paramNames && ("t" in paramNames || "p" in paramNames))

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")
}
