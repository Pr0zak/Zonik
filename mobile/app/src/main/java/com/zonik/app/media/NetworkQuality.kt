package com.zonik.app.media

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities

/**
 * True when the active network is safe to spend full bandwidth on.
 *
 * NOT_METERED is the honest signal here: a wired TV box reports no WIFI transport, so a
 * transport-only test quietly hands every Google TV the cellular bitrate. The transports
 * are kept as a fallback for networks that never report the capability at all.
 *
 * Lives outside both PlaybackManager and ZonikMediaService because the two of them each
 * build stream URLs and must agree on the answer.
 */
fun Context.isUnmeteredNetwork(): Boolean {
    val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return false
    val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
    return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
        || caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
}
