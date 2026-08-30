package com.zonik.app.media

/**
 * Browse-tree media items are published as `track:<id>` so the browse tree can tell node
 * kinds apart. That prefix must never survive into a [com.zonik.core.model.Track] id or the
 * persisted queue — it is not a track id, and anything that later looks it up finds nothing.
 */
const val TRACK_ID_PREFIX = "track:"

/** The bare track id behind a player media id, browse-tree prefix or not. */
fun bareTrackId(mediaId: String): String = mediaId.removePrefix(TRACK_ID_PREFIX)
