package com.zonik.core.auth

import com.zonik.core.model.ServerConfig
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject

/** Wire models for /api/auth/… and /api/pair/… plus the LAN discovery reply. */

@Serializable
data class AuthStatus(
    @SerialName("needs_setup") val needsSetup: Boolean = false,
    val enforce: Boolean = false,
    val version: String? = null,
    @SerialName("server_name") val serverName: String? = null,
    val url: String? = null,
)

@Serializable
data class AuthUser(
    val id: String? = null,
    val username: String,
    @SerialName("display_name") val displayName: String? = null,
    val role: String? = null,
    @SerialName("is_admin") val isAdmin: Boolean = false,
    @SerialName("auth_method") val authMethod: String? = null,
) {
    val shownName: String get() = displayName?.takeIf { it.isNotBlank() } ?: username
}

@Serializable
data class DeviceLoginRequest(
    val username: String,
    val password: String,
    val label: String? = null,
    val platform: String? = null,
)

@Serializable
data class DeviceLoginResponse(val token: String, val user: AuthUser)

@Serializable
data class DeviceTokenRequest(val label: String? = null, val platform: String? = null)

@Serializable
data class DeviceRef(val id: String, val label: String? = null, val platform: String? = null)

@Serializable
data class DeviceTokenResponse(val token: String, val device: DeviceRef? = null, val user: AuthUser? = null)

/** One row of GET /api/auth/devices (sessions and device tokens). */
@Serializable
data class DeviceItem(
    val id: String,
    val kind: String? = null,
    val label: String? = null,
    val platform: String? = null,
    val current: Boolean = false,
)

@Serializable
data class PairCreateRequest(val label: String? = null, val platform: String? = null)

@Serializable
data class PairCodeResponse(val code: String, val expires: String? = null)

/** GET /api/pair/{code}: pending | expired | ready (ready carries the config). */
@Serializable
data class PairPollResponse(
    val status: String,
    val url: String? = null,
    val username: String? = null,
    @SerialName("api_key") val apiKey: String? = null,
    @SerialName("device_token") val deviceToken: String? = null,
    @SerialName("display_name") val displayName: String? = null,
) {
    val isReady: Boolean get() = status == "ready"
    val isExpired: Boolean get() = status == "expired"

    /**
     * The config to save once ready, or null when the reply is not ready or lacks what is
     * needed: a username and at least one credential. [fallbackUrl] (the server the TV polled)
     * is used when the reply carries no url.
     */
    fun toServerConfig(fallbackUrl: String? = null): ServerConfig? {
        if (!isReady) return null
        val url = (url?.takeIf { it.isNotBlank() } ?: fallbackUrl)?.trim()?.trimEnd('/') ?: return null
        val user = username?.takeIf { it.isNotBlank() } ?: return null
        val token = deviceToken?.takeIf { it.isNotBlank() }
        val key = apiKey?.takeIf { it.isNotBlank() }
        if (token == null && key == null) return null
        return ServerConfig(url = url, username = user, apiKey = key ?: "", deviceToken = token)
    }
}

/** GET /api/pair/{code}/info. */
@Serializable
data class PairInfo(
    val status: String,
    val label: String? = null,
    val platform: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val expires: String? = null,
) {
    val isPending: Boolean get() = status == "pending"
}

@Serializable
data class PairApproveRequest(val label: String? = null)

@Serializable
data class PairApproveResponse(val status: String, val device: DeviceRef? = null)

/** A Zonik server seen on the LAN. [url] is the de-duplication key. */
data class DiscoveredServer(
    val url: String,
    val name: String? = null,
    val version: String? = null,
    val source: Source,
) {
    enum class Source { MDNS, UDP, PROBE, MANUAL }

    val host: String get() = ServerUrlNormalizer.displayHost(url)
    val title: String get() = name?.takeIf { it.isNotBlank() } ?: "Zonik"
}

object AuthJson {
    val json: Json = Json { ignoreUnknownKeys = true; isLenient = true; coerceInputValues = true }

    /** UDP probe reply `{"zonik":1,"name","version","url"}` → server, else null. */
    fun parseProbeReply(text: String): DiscoveredServer? = try {
        val obj = json.parseToJsonElement(text).jsonObject
        val marker = (obj["zonik"] as? JsonPrimitive)?.contentOrNull
        val url = (obj["url"] as? JsonPrimitive)?.contentOrNull?.trim()?.trimEnd('/')
        if (marker != "1" || url.isNullOrBlank() || !url.startsWith("http")) null
        else DiscoveredServer(
            url = url,
            name = (obj["name"] as? JsonPrimitive)?.contentOrNull,
            version = (obj["version"] as? JsonPrimitive)?.contentOrNull,
            source = DiscoveredServer.Source.UDP,
        )
    } catch (_: Exception) {
        null
    }

    /**
     * FastAPI's error body `{"detail": "..."}` (or a validation list) → readable text, else
     * null.
     */
    fun errorDetail(body: String?): String? {
        if (body.isNullOrBlank()) return null
        return try {
            val obj = json.parseToJsonElement(body) as? JsonObject ?: return null
            when (val d = obj["detail"]) {
                is JsonPrimitive -> d.contentOrNull?.takeIf { it.isNotBlank() }
                is JsonArray -> d.mapNotNull { el ->
                    ((el as? JsonObject)?.get("msg") as? JsonPrimitive)?.contentOrNull
                }.joinToString("; ").takeIf { it.isNotBlank() }
                else -> null
            }
        } catch (_: Exception) {
            null
        }
    }
}
