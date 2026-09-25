package com.zonik.app.media

/**
 * Browse-tree media items are published as `track:<id>` so the browse tree can tell node
 * kinds apart. That prefix must never survive into a [com.zonik.core.model.Track] id or the
 * persisted queue — it is not a track id, and anything that later looks it up finds nothing.
 */
const val TRACK_ID_PREFIX = "track:"

/** The bare track id behind a player media id, browse-tree prefix or not. */
fun bareTrackId(mediaId: String): String = mediaId.removePrefix(TRACK_ID_PREFIX)

/**
 * A catalog song offered in Android Auto search results ("Get: <title>"). Tapping it starts
 * a server download; it never reaches the timeline — a [PREVIEW_ID_PREFIX] item does.
 */
const val GET_ID_PREFIX = "get:"

/**
 * The 30 s catalog preview that plays while a download runs, replaced by the real track when
 * the download completes. Not a track id: scrobbling, now-playing, starring and the persisted
 * queue must all skip it.
 */
const val PREVIEW_ID_PREFIX = "preview:"

fun isPreviewId(mediaId: String?): Boolean = mediaId?.startsWith(PREVIEW_ID_PREFIX) == true
