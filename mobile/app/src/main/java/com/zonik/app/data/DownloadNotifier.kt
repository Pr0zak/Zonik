package com.zonik.app.data

import android.Manifest
import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.zonik.app.ZonikApplication
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/** One download as the notifier sees it. */
data class DownloadNotice(
    val key: String,
    val title: String,
    val active: Boolean,
    val done: Boolean,
    val failed: Boolean,
    val pct: Int,
    val detail: String?
)

/**
 * Posts download progress and outcomes on the "Downloads" channel: one ongoing
 * notification while anything is in flight, then a single "Ready" or
 * "Couldn't get" notification per download. Silent when the user hasn't
 * granted notification permission.
 */
@Singleton
class DownloadNotifier @Inject constructor(
    @ApplicationContext private val context: Context
) {
    private companion object {
        const val PROGRESS_ID = 4100
        const val OUTCOME_BASE_ID = 4200
    }

    private val manager = NotificationManagerCompat.from(context)
    private val announced = mutableSetOf<String>()

    private fun allowed(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED

    private fun openApp(): PendingIntent? {
        val intent = context.packageManager.getLaunchIntentForPackage(context.packageName) ?: return null
        return PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    @SuppressLint("MissingPermission") // checked in allowed()
    @Synchronized
    fun update(items: List<DownloadNotice>) {
        if (!allowed()) return
        val active = items.filter { it.active }
        if (active.isEmpty()) {
            manager.cancel(PROGRESS_ID)
        } else {
            val title = if (active.size == 1) active[0].title else "Getting ${active.size} tracks"
            val detail = if (active.size == 1) active[0].detail else active.joinToString(" · ") { it.title }
            val pct = active.map { it.pct }.average().toInt()
            val indeterminate = active.all { it.pct <= 0 }
            manager.notify(
                PROGRESS_ID,
                NotificationCompat.Builder(context, ZonikApplication.DOWNLOAD_CHANNEL_ID)
                    .setSmallIcon(android.R.drawable.stat_sys_download)
                    .setContentTitle(title)
                    .setContentText(detail)
                    .setProgress(100, pct, indeterminate)
                    .setOngoing(true)
                    .setOnlyAlertOnce(true)
                    .setSilent(true)
                    .setContentIntent(openApp())
                    .build()
            )
        }
        for (item in items) {
            if (!(item.done || item.failed) || !announced.add(item.key)) continue
            manager.notify(
                OUTCOME_BASE_ID + (item.key.hashCode() and 0xFFFF),
                NotificationCompat.Builder(context, ZonikApplication.DOWNLOAD_CHANNEL_ID)
                    .setSmallIcon(if (item.done) android.R.drawable.stat_sys_download_done else android.R.drawable.stat_notify_error)
                    .setContentTitle(if (item.done) "Ready: ${item.title}" else "Couldn't get ${item.title}")
                    .setContentText(item.detail)
                    .setStyle(NotificationCompat.BigTextStyle().bigText(item.detail))
                    .setAutoCancel(true)
                    .setContentIntent(openApp())
                    .build()
            )
        }
    }

    /** Forget a download so a retry announces its outcome again. */
    @Synchronized
    fun reset(key: String) {
        announced.remove(key)
    }
}
