package com.zonik.wear.media

import android.os.Bundle
import androidx.media3.common.MediaItem

/**
 * Endless Quick Mix: items tagged here are topped up by [ZonikWearMediaService] with more
 * random songs as the queue runs low. The tag lives on the items rather than in a service
 * flag, so any other queue replacing the mix ends it automatically. MediaMetadata extras
 * survive the controller → service hop.
 */
object EndlessMix {
    private const val EXTRA = "endless_mix"

    /** Fetch another batch once this few tracks are left. */
    const val LOW_WATER = 10
    const val BATCH = 50

    fun tag(items: List<MediaItem>): List<MediaItem> = items.map { item ->
        val extras = Bundle(item.mediaMetadata.extras ?: Bundle.EMPTY)
        extras.putBoolean(EXTRA, true)
        item.buildUpon()
            .setMediaMetadata(item.mediaMetadata.buildUpon().setExtras(extras).build())
            .build()
    }

    fun isTagged(item: MediaItem?): Boolean =
        item?.mediaMetadata?.extras?.getBoolean(EXTRA) == true
}
