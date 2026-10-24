package com.zonik.core.model

import kotlinx.serialization.Serializable

@Serializable
data class Artist(
    val id: String,
    val name: String,
    val albumCount: Int = 0,
    val coverArt: String? = null,
    val starred: Boolean = false
)

@Serializable
data class Album(
    val id: String,
    val name: String,
    val artist: String = "",
    val artistId: String? = null,
    val coverArt: String? = null,
    val year: Int? = null,
    val songCount: Int = 0,
    val duration: Int = 0,
    val genre: String? = null,
    val starred: Boolean = false,
    /** Server-side date added (ISO-8601 UTC). Sorts correctly lexicographically. */
    val created: String? = null
)

@Serializable
data class Track(
    val id: String,
    val title: String,
    val artist: String = "",
    val artistId: String? = null,
    val album: String = "",
    val albumId: String? = null,
    val coverArt: String? = null,
    val duration: Int = 0,
    val track: Int? = null,
    val year: Int? = null,
    val genre: String? = null,
    val bitRate: Int? = null,
    val size: Long? = null,
    val suffix: String? = null,
    val contentType: String? = null,
    val transcodedSuffix: String? = null,
    val transcodedContentType: String? = null,
    val path: String? = null,
    val starred: Boolean = false,
    val markedForDeletion: Boolean = false,
    val offlineCached: Boolean = false,
    val playCount: Int = 0,
    val played: String? = null,
    /** Server-side date added (ISO-8601 UTC). Sorts correctly lexicographically. */
    val created: String? = null
)

@Serializable
data class Playlist(
    val id: String,
    val name: String,
    val songCount: Int = 0,
    val duration: Int = 0,
    val coverArt: String? = null,
    val owner: String? = null
)

@Serializable
data class Genre(
    val name: String,
    val songCount: Int = 0,
    val albumCount: Int = 0
)

/**
 * Where the app talks to and how it signs in.
 *
 * [apiKey] is the legacy Subsonic key (sent as u/t/s token auth). [deviceToken] is a per-device
 * token minted by the server (`/api/auth/device`, `/api/auth/devices`, TV pairing); when present
 * it is sent as OpenSubsonic `apiKey=` and the legacy key is not sent at all. Configs saved by
 * older releases load with a null token and keep working with the key. Build auth params with
 * [com.zonik.core.auth.SubsonicAuth], never by hand.
 */
data class ServerConfig(
    val url: String,
    val username: String,
    val apiKey: String,
    val deviceToken: String? = null,
) {
    val hasDeviceToken: Boolean get() = !deviceToken.isNullOrBlank()

    /** True when there is something to sign requests with. */
    val hasCredentials: Boolean get() = hasDeviceToken || apiKey.isNotBlank()

    override fun toString(): String =
        "ServerConfig(url=$url, username=$username, apiKey=${if (apiKey.isBlank()) "none" else "***"}, " +
            "deviceToken=${if (hasDeviceToken) "***" else "none"})"
}

enum class RepeatMode { OFF, ALL, ONE }
enum class ShuffleMode { OFF, SHUFFLE, TRUE_RANDOM }
