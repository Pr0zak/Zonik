package com.zonik.app.data.auth

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.NetworkCapabilities
import android.os.Build
import android.provider.Settings
import com.zonik.app.ui.util.isTvDevice
import java.net.Inet4Address

/** How this device names itself to the server (device-token labels) and where it is on the LAN. */
object DeviceIdentity {

    /** "Pixel 9a" — Build.MODEL, prefixed with the maker when the model doesn't already say it. */
    fun model(): String {
        val model = Build.MODEL?.trim().orEmpty()
        val maker = Build.MANUFACTURER?.trim().orEmpty()
        return when {
            model.isEmpty() -> maker.ifEmpty { "Android" }
            maker.isEmpty() || model.startsWith(maker, ignoreCase = true) -> model
            maker.equals("Google", ignoreCase = true) -> model
            else -> "${maker.replaceFirstChar { it.uppercase() }} $model"
        }
    }

    /** The name the user gave the device in system settings, if any (API 25+). */
    fun userDeviceName(context: Context): String? = try {
        Settings.Global.getString(context.contentResolver, Settings.Global.DEVICE_NAME)?.trim()?.takeIf { it.isNotEmpty() }
    } catch (_: Exception) {
        null
    }

    fun isTv(context: Context): Boolean = context.isTvDevice()

    fun platform(context: Context): String = if (isTv(context)) "tv" else "android"

    /** Label for this device's token: the TV's own name ("Living Room TV") or "<model> TV"; the phone model. */
    fun label(context: Context): String = if (isTv(context)) {
        userDeviceName(context) ?: "${model()} TV"
    } else {
        model()
    }

    /**
     * The device's IPv4 on the active Wi-Fi/Ethernet network ("10.0.0.37"), or null. Used for
     * the `.205` shorthand and the UDP probe's subnet broadcast.
     */
    fun lanIpv4(context: Context): String? = try {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val candidates = buildList {
            cm?.activeNetwork?.let { add(it) }
            @Suppress("DEPRECATION")
            cm?.allNetworks?.forEach { if (it !in this) add(it) }
        }
        candidates.firstNotNullOfOrNull { network ->
            val caps = cm?.getNetworkCapabilities(network) ?: return@firstNotNullOfOrNull null
            val lan = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
            if (!lan) return@firstNotNullOfOrNull null
            ipv4Of(cm.getLinkProperties(network))
        }
    } catch (_: Exception) {
        null
    }

    private fun ipv4Of(lp: LinkProperties?): String? =
        lp?.linkAddresses?.map { it.address }?.firstOrNull { it is Inet4Address && !it.isLoopbackAddress }?.hostAddress
}
