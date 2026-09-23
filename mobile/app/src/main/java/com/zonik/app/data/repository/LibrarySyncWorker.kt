package com.zonik.app.data.repository

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.zonik.app.data.DebugLog
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.first
import java.util.concurrent.TimeUnit

/** Background library sync on the interval chosen in Settings → Sync. */
@HiltWorker
class LibrarySyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val syncManager: SyncManager,
    private val settingsRepository: SettingsRepository,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        if (!settingsRepository.isLoggedIn.first()) return Result.success()
        DebugLog.d("Sync", "Scheduled sync starting")
        return if (syncManager.fullSync(background = true)) Result.success() else Result.retry()
    }

    companion object {
        private const val WORK_NAME = "library_sync"

        /** Schedules (or cancels, for interval 0 = Off) the periodic sync. Safe to call
         *  repeatedly: UPDATE keeps the existing schedule unless the settings changed.
         *  WorkManager's floor for periodic work is 15 minutes. */
        fun schedule(context: Context, intervalMinutes: Int, wifiOnly: Boolean) {
            val wm = WorkManager.getInstance(context)
            if (intervalMinutes <= 0) {
                wm.cancelUniqueWork(WORK_NAME)
                DebugLog.d("Sync", "Scheduled sync off")
                return
            }
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(if (wifiOnly) NetworkType.UNMETERED else NetworkType.CONNECTED)
                .setRequiresBatteryNotLow(true)
                .build()
            val request = PeriodicWorkRequestBuilder<LibrarySyncWorker>(
                intervalMinutes.coerceAtLeast(15).toLong(), TimeUnit.MINUTES
            ).setConstraints(constraints).build()
            wm.enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
            DebugLog.d("Sync", "Scheduled sync every ${intervalMinutes}m${if (wifiOnly) " (Wi-Fi only)" else ""}")
        }
    }
}
