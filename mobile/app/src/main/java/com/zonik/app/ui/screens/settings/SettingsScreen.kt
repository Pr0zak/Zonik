package com.zonik.app.ui.screens.settings

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.text.format.DateUtils
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.rememberVectorPainter
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.zonik.app.data.DebugLog
import com.zonik.app.ui.theme.ZonikShapes
import com.zonik.app.ui.util.formatLargeDuration
import com.zonik.app.ui.util.formatLargeFileSize

/** A destructive action waiting for the user to confirm it. */
private data class ConfirmRequest(
    val title: String,
    val message: String,
    val confirmLabel: String,
    val onConfirm: () -> Unit,
)

@Composable
fun SettingsScreen(
    onDisconnected: () -> Unit,
    onNavigateToStats: () -> Unit = {},
    viewModel: SettingsViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var confirm by remember { mutableStateOf<ConfirmRequest?>(null) }
    val askToConfirm: (ConfirmRequest) -> Unit = { confirm = it }

    com.zonik.app.ui.theme.WithNeutralScheme {
    Scaffold(
        containerColor = MaterialTheme.colorScheme.surface,
        topBar = {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .height(64.dp)
                    .padding(start = 16.dp, end = 4.dp),
                contentAlignment = Alignment.CenterStart
            ) {
                Text(text = "Settings", style = MaterialTheme.typography.titleLarge)
            }
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(bottom = 32.dp)
        ) {
            SettingsGroup("Server") {
                ServerSection(viewModel, uiState, onDisconnected, askToConfirm)
            }
            SettingsGroup("Playback") {
                PlaybackSection(viewModel, uiState)
            }
            SettingsGroup("Equalizer") {
                EqualizerSection(viewModel, uiState)
            }
            SettingsGroup("Library") {
                LibrarySection(viewModel, uiState, onNavigateToStats)
            }
            SettingsGroup("Offline downloads") {
                OfflineSection(viewModel, askToConfirm)
            }
            SettingsGroup("Storage") {
                StorageSection(viewModel, uiState, askToConfirm)
            }
            SettingsGroup("Devices") {
                DevicesSection(viewModel)
            }
            SettingsGroup("About") {
                AboutSection(viewModel)
            }
            SettingsGroup("Troubleshooting") {
                TroubleshootingSection(viewModel, askToConfirm)
            }
        }
    }

    confirm?.let { request ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text(request.title) },
            text = { Text(request.message) },
            confirmButton = {
                TextButton(
                    onClick = { request.onConfirm(); confirm = null },
                    colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)
                ) { Text(request.confirmLabel) }
            },
            dismissButton = {
                TextButton(onClick = { confirm = null }) { Text("Cancel") }
            }
        )
    }
    }
}

// region Sections

@Composable
private fun ServerSection(
    viewModel: SettingsViewModel,
    uiState: SettingsUiState,
    onDisconnected: () -> Unit,
    askToConfirm: (ConfirmRequest) -> Unit,
) {
    var editing by remember { mutableStateOf<ServerField?>(null) }
    val isTesting by viewModel.isTestingConnection.collectAsStateWithLifecycle()
    val testResult by viewModel.connectionTestResult.collectAsStateWithLifecycle()

    SettingRow(
        title = "Server address",
        summary = uiState.serverUrl.ifEmpty { "Not connected" },
        icon = Icons.Default.Dns,
        onClick = { editing = ServerField.Url },
        trailing = { EditHint() }
    )
    GroupDivider()
    SettingRow(
        title = "Username",
        summary = uiState.username.ifEmpty { "Not set" },
        icon = Icons.Default.Person,
        onClick = { editing = ServerField.Username },
        trailing = { EditHint() }
    )
    GroupDivider()
    SettingRow(
        title = "Password or API key",
        summary = "Saved · tap to change",
        icon = Icons.Default.Key,
        onClick = { editing = ServerField.ApiKey },
        trailing = { EditHint() }
    )
    GroupDivider()
    SettingRow(
        title = "Test connection",
        summary = when {
            isTesting -> "Checking…"
            testResult != null -> testResult
            else -> buildString {
                append("Server ")
                append(uiState.serverVersion.ifEmpty { "version unknown" })
                uiState.serverType?.let { append(" · $it") }
            }
        },
        summaryColor = when {
            isTesting || testResult == null -> null
            testResult == "Connected" -> MaterialTheme.colorScheme.primary
            else -> MaterialTheme.colorScheme.error
        },
        icon = Icons.Default.NetworkCheck,
        enabled = !isTesting,
        onClick = viewModel::testConnection,
        trailing = if (isTesting) {
            { CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp) }
        } else null
    )
    if (testResult != null) {
        LaunchedEffect(testResult) {
            kotlinx.coroutines.delay(5000)
            viewModel.clearConnectionTestResult()
        }
    }
    GroupDivider()
    SettingRow(
        title = "Disconnect",
        summary = "Sign out of this server",
        icon = Icons.Default.Logout,
        titleColor = MaterialTheme.colorScheme.error,
        onClick = {
            askToConfirm(
                ConfirmRequest(
                    title = "Disconnect from server?",
                    message = "You'll need to enter the server address and your login again to use the app.",
                    confirmLabel = "Disconnect",
                    onConfirm = { viewModel.disconnect(); onDisconnected() }
                )
            )
        }
    )

    editing?.let { field ->
        ServerFieldDialog(
            field = field,
            initialValue = when (field) {
                ServerField.Url -> uiState.serverUrl
                ServerField.Username -> uiState.username
                ServerField.ApiKey -> ""
            },
            onDismiss = { editing = null },
            onSave = { value ->
                when (field) {
                    ServerField.Url -> viewModel.updateServerUrl(value)
                    ServerField.Username -> viewModel.updateUsername(value)
                    ServerField.ApiKey -> viewModel.updateApiKey(value)
                }
                editing = null
            }
        )
    }
}

private enum class ServerField(val label: String) {
    Url("Server address"),
    Username("Username"),
    ApiKey("Password or API key"),
}

@Composable
private fun ServerFieldDialog(
    field: ServerField,
    initialValue: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    var value by remember { mutableStateOf(initialValue) }
    var reveal by remember { mutableStateOf(false) }
    val trimmed = value.trim()
    val error = when {
        trimmed.isEmpty() -> null
        field == ServerField.Url && !(trimmed.startsWith("http://") || trimmed.startsWith("https://")) ->
            "Start with http:// or https://"
        else -> null
    }
    val canSave = trimmed.isNotEmpty() && error == null

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Change ${field.label.lowercase()}") },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                label = { Text(field.label) },
                placeholder = if (field == ServerField.Url) {
                    { Text("https://music.example.com") }
                } else null,
                singleLine = true,
                isError = error != null,
                supportingText = error?.let { { Text(it) } },
                keyboardOptions = KeyboardOptions(
                    keyboardType = when (field) {
                        ServerField.Url -> KeyboardType.Uri
                        ServerField.Username -> KeyboardType.Text
                        ServerField.ApiKey -> KeyboardType.Password
                    },
                    autoCorrectEnabled = false,
                    imeAction = ImeAction.Done,
                ),
                visualTransformation = if (field == ServerField.ApiKey && !reveal) {
                    PasswordVisualTransformation()
                } else VisualTransformation.None,
                trailingIcon = if (field == ServerField.ApiKey) {
                    {
                        IconButton(onClick = { reveal = !reveal }) {
                            Icon(
                                if (reveal) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                contentDescription = if (reveal) "Hide" else "Show"
                            )
                        }
                    }
                } else null,
                modifier = Modifier.fillMaxWidth()
            )
        },
        confirmButton = {
            TextButton(onClick = { onSave(trimmed) }, enabled = canSave) { Text("Save") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        }
    )
}

@Composable
private fun PlaybackSection(viewModel: SettingsViewModel, uiState: SettingsUiState) {
    ChoiceRow(
        title = "Quality on Wi-Fi",
        icon = Icons.Default.Wifi,
        options = BITRATE_OPTIONS,
        selected = uiState.wifiBitrate,
        onSelect = viewModel::setWifiBitrate
    )
    GroupDivider()
    ChoiceRow(
        title = "Quality on mobile data",
        icon = Icons.Default.SignalCellularAlt,
        options = BITRATE_OPTIONS,
        selected = uiState.cellularBitrate,
        onSelect = viewModel::setCellularBitrate
    )
    GroupDivider()
    SwitchRow(
        title = "Adaptive quality",
        summary = "Lower the quality automatically when the connection is slow",
        icon = Icons.Default.Speed,
        checked = uiState.adaptiveBitrate,
        onCheckedChange = viewModel::setAdaptiveBitrate
    )
    GroupDivider()
    ChoiceRow(
        title = "Preload upcoming tracks",
        hint = "Downloads the next tracks ahead of time so playback doesn't stall",
        icon = Icons.Default.FastForward,
        options = listOf(0 to "Off", 1 to "1 track", 2 to "2 tracks", 3 to "3 tracks", 5 to "5 tracks", 10 to "10 tracks"),
        selected = uiState.cacheReadAhead,
        onSelect = viewModel::setCacheReadAhead
    )
    GroupDivider()
    SwitchRow(
        title = "Waveform seek bar",
        summary = "Show the track's waveform on the Now Playing seek bar",
        icon = Icons.Default.GraphicEq,
        checked = uiState.visualizerEnabled,
        onCheckedChange = viewModel::setVisualizerEnabled
    )
    GroupDivider()
    SwitchRow(
        title = "Keep screen on",
        summary = "While Now Playing is open",
        icon = Icons.Default.Brightness7,
        checked = uiState.keepScreenOn,
        onCheckedChange = viewModel::setKeepScreenOn
    )
}

private val BITRATE_OPTIONS = listOf(
    0 to "Original (no limit)",
    320 to "320 kbps",
    256 to "256 kbps",
    192 to "192 kbps",
    128 to "128 kbps",
    64 to "64 kbps (data saver)",
)

private val EQ_PRESETS = listOf("Normal", "Classical", "Dance", "Flat", "Folk", "Heavy Metal", "Hip Hop", "Jazz", "Pop", "Rock")
private val EQ_BANDS = listOf("60 Hz", "230 Hz", "910 Hz", "3.6 kHz", "14 kHz")

@Composable
private fun EqualizerSection(viewModel: SettingsViewModel, uiState: SettingsUiState) {
    val context = LocalContext.current

    SwitchRow(
        title = "Equalizer",
        summary = "Shape the sound with a preset or your own curve",
        icon = Icons.Default.Tune,
        checked = uiState.eqEnabled,
        onCheckedChange = viewModel::setEqEnabled
    )
    GroupDivider()
    ChoiceRow(
        title = "Preset",
        icon = Icons.Default.MusicNote,
        options = EQ_PRESETS.mapIndexed { i, name -> i to name } + (-1 to "Custom"),
        selected = uiState.eqPreset,
        enabled = uiState.eqEnabled,
        onSelect = { preset -> if (preset < 0) viewModel.useCustomEq() else viewModel.setEqPreset(preset) }
    )
    if (uiState.eqEnabled && uiState.eqPreset < 0) {
        val saved = uiState.eqBandLevels?.split(",")?.mapNotNull { it.toShortOrNull() } ?: emptyList()
        Column(modifier = Modifier.padding(start = 20.dp, end = 12.dp, bottom = 8.dp)) {
            EQ_BANDS.forEachIndexed { index, label ->
                // Local while dragging; saved (and applied) once the finger lifts, rather than
                // writing settings on every pixel of movement.
                val savedLevel = saved.getOrElse(index) { 0 }.toFloat()
                var level by remember(savedLevel) { mutableFloatStateOf(savedLevel) }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(label, style = MaterialTheme.typography.labelMedium, modifier = Modifier.width(60.dp))
                    Slider(
                        value = level,
                        onValueChange = { level = it },
                        onValueChangeFinished = { viewModel.setEqBandLevel(index, level.toInt().toShort()) },
                        valueRange = -1500f..1500f,
                        modifier = Modifier.weight(1f)
                    )
                    Text(
                        "%+.1f dB".format(level / 100f),
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.width(64.dp).padding(start = 8.dp)
                    )
                }
            }
            TextButton(onClick = viewModel::useCustomEq, modifier = Modifier.align(Alignment.End)) {
                Text("Reset to flat")
            }
        }
    }
    GroupDivider()
    SettingRow(
        title = "System equalizer",
        summary = "Open your phone's own sound settings",
        icon = Icons.Default.OpenInNew,
        onClick = {
            try {
                val intent = android.content.Intent(android.media.audiofx.AudioEffect.ACTION_DISPLAY_AUDIO_EFFECT_CONTROL_PANEL)
                intent.putExtra(android.media.audiofx.AudioEffect.EXTRA_PACKAGE_NAME, context.packageName)
                intent.putExtra(android.media.audiofx.AudioEffect.EXTRA_CONTENT_TYPE, android.media.audiofx.AudioEffect.CONTENT_TYPE_MUSIC)
                if (intent.resolveActivity(context.packageManager) != null) {
                    context.startActivity(intent)
                } else {
                    Toast.makeText(context, "No system equalizer on this phone", Toast.LENGTH_SHORT).show()
                }
            } catch (_: Exception) {}
        }
    )
}

@Composable
private fun LibrarySection(viewModel: SettingsViewModel, uiState: SettingsUiState, onNavigateToStats: () -> Unit) {
    val syncState by viewModel.syncState.collectAsStateWithLifecycle()
    val stats = uiState.libraryStats

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 16.dp, bottom = 8.dp),
        horizontalArrangement = Arrangement.SpaceEvenly
    ) {
        StatItem(label = "Tracks", value = "%,d".format(stats.trackCount))
        StatItem(label = "Albums", value = "%,d".format(stats.albumCount))
        StatItem(label = "Artists", value = "%,d".format(stats.artistCount))
    }
    SettingRow(
        title = "Library statistics",
        summary = "%,d genres · %s · %s".format(
            stats.genreCount,
            formatLargeDuration(stats.totalDurationSeconds),
            formatLargeFileSize(stats.totalSizeBytes)
        ),
        icon = Icons.Default.BarChart,
        onClick = onNavigateToStats,
        trailing = { Chevron() }
    )
    GroupDivider()
    ChoiceRow(
        title = "Automatic sync",
        hint = "Keeps the library on this phone up to date with the server",
        icon = Icons.Default.Sync,
        options = listOf(0 to "Off", 15 to "Every 15 minutes", 60 to "Every hour", 360 to "Every 6 hours", 1440 to "Once a day"),
        selected = uiState.syncIntervalMinutes,
        onSelect = viewModel::setSyncInterval
    )
    GroupDivider()
    SwitchRow(
        title = "Only on Wi-Fi",
        summary = if (uiState.syncIntervalMinutes == 0) "Turn on automatic sync to use this"
        else "Automatic sync waits for Wi-Fi",
        icon = Icons.Default.Wifi,
        checked = uiState.wifiOnly,
        enabled = uiState.syncIntervalMinutes != 0,
        onCheckedChange = viewModel::setWifiOnly
    )
    GroupDivider()
    val lastSynced = if (uiState.lastSyncTime > 0L) {
        "Last synced " + DateUtils.getRelativeTimeSpanString(
            uiState.lastSyncTime, System.currentTimeMillis(), DateUtils.MINUTE_IN_MILLIS
        )
    } else "Never synced"
    SettingRow(
        title = if (syncState.isSyncing) syncState.phase.ifEmpty { "Syncing…" } else "Sync now",
        summary = when {
            syncState.isSyncing -> syncState.detail.ifEmpty { lastSynced }
            syncState.error != null -> "Last sync failed: ${syncState.error}"
            else -> lastSynced
        },
        summaryColor = if (!syncState.isSyncing && syncState.error != null) MaterialTheme.colorScheme.error else null,
        icon = Icons.Default.CloudSync,
        enabled = !syncState.isSyncing,
        onClick = viewModel::syncNow,
        trailing = if (syncState.isSyncing) {
            { CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp) }
        } else null
    )
}

@Composable
private fun OfflineSection(viewModel: SettingsViewModel, askToConfirm: (ConfirmRequest) -> Unit) {
    val enabled by viewModel.offlineCacheEnabled.collectAsStateWithLifecycle()
    val autoCacheQueue by viewModel.autoCacheQueue.collectAsStateWithLifecycle()
    val autoCacheFavorites by viewModel.autoCacheFavorites.collectAsStateWithLifecycle()
    val limitMb by viewModel.offlineStorageLimitMb.collectAsStateWithLifecycle()
    val usedBytes by viewModel.offlineStorageUsedBytes.collectAsStateWithLifecycle()

    SwitchRow(
        title = "Offline downloads",
        summary = "Keep tracks on this phone to play without a connection",
        icon = Icons.Default.CloudDownload,
        checked = enabled,
        onCheckedChange = viewModel::setOfflineCacheEnabled
    )
    if (!enabled) return

    GroupDivider()
    SwitchRow(
        title = "Download the queue",
        summary = "Save tracks you queue up, in the background",
        icon = Icons.Default.QueueMusic,
        checked = autoCacheQueue,
        onCheckedChange = viewModel::setAutoCacheQueue
    )
    GroupDivider()
    SwitchRow(
        title = "Download favorites",
        summary = "Save starred tracks after each sync",
        icon = Icons.Default.Favorite,
        checked = autoCacheFavorites,
        onCheckedChange = viewModel::setAutoCacheFavorites
    )
    GroupDivider()
    ChoiceRow(
        title = "Storage limit",
        hint = "${formatLargeFileSize(usedBytes)} used",
        icon = Icons.Default.Sd,
        options = listOf(256, 512, 1024, 2048, 5120, 10240, 20480, 51200).map { it to mbLabel(it) } + (0 to "No limit"),
        selected = limitMb,
        onSelect = viewModel::setOfflineStorageLimitMb
    )
    if (limitMb > 0 && usedBytes > 0) {
        UsageBar(used = usedBytes, limitBytes = limitMb * 1024L * 1024L)
    }
    GroupDivider()
    SettingRow(
        title = "Delete downloads",
        summary = "Remove every downloaded track from this phone",
        icon = Icons.Default.DeleteSweep,
        titleColor = MaterialTheme.colorScheme.error,
        enabled = usedBytes > 0,
        onClick = {
            askToConfirm(
                ConfirmRequest(
                    title = "Delete all downloads?",
                    message = "${formatLargeFileSize(usedBytes)} of downloaded tracks will be removed. They'll stream from the server again.",
                    confirmLabel = "Delete",
                    onConfirm = viewModel::clearOfflineCache
                )
            )
        }
    )
}

@Composable
private fun StorageSection(viewModel: SettingsViewModel, uiState: SettingsUiState, askToConfirm: (ConfirmRequest) -> Unit) {
    val context = LocalContext.current

    ChoiceRow(
        title = "Streaming cache",
        hint = if (uiState.maxCacheSizeMb == 0) "Recently played tracks aren't kept"
        else "${formatLargeFileSize(uiState.cacheSizeBytes)} used · applies after restarting the app",
        icon = Icons.Default.Storage,
        options = listOf(0 to "Off", 250 to "250 MB", 500 to "500 MB", 1024 to "1 GB", 2048 to "2 GB", 5120 to "5 GB", 10240 to "10 GB"),
        selected = uiState.maxCacheSizeMb,
        onSelect = viewModel::setAudioCacheSizeMb
    )
    if (uiState.maxCacheSizeMb > 0 && uiState.cacheSizeBytes > 0) {
        UsageBar(used = uiState.cacheSizeBytes, limitBytes = uiState.maxCacheSizeMb * 1024L * 1024L)
    }
    GroupDivider()
    SettingRow(
        title = "Clear streaming cache",
        summary = "Recently played tracks will download again next time",
        icon = Icons.Default.DeleteSweep,
        enabled = uiState.cacheSizeBytes > 0,
        onClick = {
            askToConfirm(
                ConfirmRequest(
                    title = "Clear streaming cache?",
                    message = "Frees ${formatLargeFileSize(uiState.cacheSizeBytes)}. Downloads you kept for offline aren't affected.",
                    confirmLabel = "Clear",
                    onConfirm = viewModel::clearCache
                )
            )
        }
    )
    GroupDivider()
    ChoiceRow(
        title = "Artwork cache",
        hint = "Applies after restarting the app",
        icon = Icons.Default.Image,
        options = listOf(100 to "100 MB", 250 to "250 MB", 500 to "500 MB", 1024 to "1 GB"),
        selected = uiState.coverArtCacheSizeMb,
        onSelect = viewModel::setCoverArtCacheSizeMb
    )
    GroupDivider()
    SettingRow(
        title = "Clear artwork cache",
        summary = "Album covers will download again as you browse",
        icon = Icons.Default.HideImage,
        onClick = {
            askToConfirm(
                ConfirmRequest(
                    title = "Clear artwork cache?",
                    message = "Album covers will download again as you browse.",
                    confirmLabel = "Clear",
                    onConfirm = { viewModel.clearCoverArtCache(context) }
                )
            )
        }
    )
}

@Composable
private fun DevicesSection(viewModel: SettingsViewModel) {
    val wearStatus by viewModel.wearPairStatus.collectAsStateWithLifecycle()
    val tabOrder by viewModel.autoTabOrder.collectAsStateWithLifecycle()
    val tabLabels = mapOf(
        "mix" to "Mix",
        "recent" to "Recently Added",
        "library" to "Library",
        "playlists" to "Playlists"
    )

    SettingRow(
        title = "Set up Wear OS watch",
        summary = wearStatus ?: "Send this server's details to your paired watch so you don't have to type them",
        icon = Icons.Default.Watch,
        onClick = viewModel::pairWatch,
        trailing = { FilledTonalButton(onClick = viewModel::pairWatch) { Text("Send") } }
    )
    GroupDivider()
    SettingRow(
        title = "Android Auto tabs",
        summary = "Order of the tabs in your car",
        icon = Icons.Default.DirectionsCar,
    )
    tabOrder.forEachIndexed { index, tabId ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 72.dp, end = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "${index + 1}",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.width(24.dp)
            )
            Text(tabLabels[tabId] ?: tabId, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
            IconButton(onClick = { viewModel.moveAutoTab(index, index - 1) }, enabled = index > 0) {
                Icon(Icons.Default.KeyboardArrowUp, contentDescription = "Move ${tabLabels[tabId] ?: tabId} up")
            }
            IconButton(onClick = { viewModel.moveAutoTab(index, index + 1) }, enabled = index < tabOrder.size - 1) {
                Icon(Icons.Default.KeyboardArrowDown, contentDescription = "Move ${tabLabels[tabId] ?: tabId} down")
            }
        }
    }
    Spacer(modifier = Modifier.height(8.dp))
}

@Composable
private fun AboutSection(viewModel: SettingsViewModel) {
    val context = LocalContext.current
    val availableUpdate by viewModel.availableUpdate.collectAsStateWithLifecycle()
    val isChecking by viewModel.isCheckingUpdate.collectAsStateWithLifecycle()
    val updateProgress by viewModel.updateProgress.collectAsStateWithLifecycle()
    val versionName = remember {
        try {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "unknown"
        } catch (_: Exception) { "unknown" }
    }

    val update = availableUpdate
    if (update != null) {
        val progress = updateProgress
        SettingRow(
            title = "Update available: v${update.version}",
            summary = when {
                progress != null -> "Downloading… ${(progress * 100).toInt()}%"
                update.releaseNotes.isNotBlank() -> update.releaseNotes.lines().first { it.isNotBlank() }
                else -> "You have v$versionName"
            },
            icon = Icons.Default.NewReleases,
            titleColor = MaterialTheme.colorScheme.primary,
            enabled = progress == null,
            onClick = viewModel::downloadUpdate,
            trailing = if (progress == null) {
                { Button(onClick = viewModel::downloadUpdate) { Text("Install") } }
            } else null
        )
        if (progress != null) {
            LinearProgressIndicator(
                progress = { progress },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 72.dp, end = 16.dp, bottom = 12.dp)
            )
        }
    } else {
        SettingRow(
            title = "Zonik v$versionName",
            summary = if (isChecking) "Checking for updates…" else "Up to date · tap to check again",
            icon = Icons.Default.Info,
            enabled = !isChecking,
            onClick = viewModel::checkForUpdate,
            trailing = if (isChecking) {
                { CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp) }
            } else null
        )
    }
    GroupDivider()
    SettingRow(
        title = "Source code",
        summary = "github.com/Pr0zak/Zonik",
        painter = painterResource(id = com.zonik.app.R.drawable.ic_github),
        onClick = {
            context.startActivity(
                android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse("https://github.com/Pr0zak/Zonik"))
            )
        },
        trailing = {
            Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    )
}

@Composable
private fun TroubleshootingSection(viewModel: SettingsViewModel, askToConfirm: (ConfirmRequest) -> Unit) {
    val context = LocalContext.current
    val isUploading by viewModel.isUploadingLogsToServer.collectAsStateWithLifecycle()
    val uploadResult by viewModel.serverUploadResult.collectAsStateWithLifecycle()
    val uploadOk = uploadResult?.startsWith("Uploaded") == true

    SettingRow(
        title = "Send logs to server",
        summary = when {
            isUploading -> "Uploading…"
            uploadResult != null -> uploadResult
            else -> "Upload this app's debug log to your Zonik server"
        },
        summaryColor = when {
            isUploading || uploadResult == null -> null
            uploadOk -> MaterialTheme.colorScheme.primary
            else -> MaterialTheme.colorScheme.error
        },
        icon = Icons.Default.CloudUpload,
        enabled = !isUploading,
        onClick = viewModel::uploadLogsToServer,
        trailing = if (isUploading) {
            { CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp) }
        } else null
    )
    GroupDivider()
    SettingRow(
        title = "Copy logs",
        summary = "Copy the debug log to the clipboard",
        icon = Icons.Default.ContentCopy,
        onClick = {
            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("Zonik Logs", DebugLog.getPersistedLogs()))
            Toast.makeText(context, "Logs copied", Toast.LENGTH_SHORT).show()
        }
    )
    GroupDivider()
    SettingRow(
        title = "Clear logs",
        summary = "Start the debug log fresh",
        icon = Icons.Default.BugReport,
        onClick = {
            askToConfirm(
                ConfirmRequest(
                    title = "Clear debug logs?",
                    message = "The log on this phone will be emptied. Anything already sent to the server stays there.",
                    confirmLabel = "Clear",
                    onConfirm = { DebugLog.clear() }
                )
            )
        }
    )
}

// endregion

// region Building blocks

@Composable
private fun SettingsGroup(title: String, content: @Composable ColumnScope.() -> Unit) {
    Text(
        text = title,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 28.dp, top = 24.dp, bottom = 8.dp)
    )
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        shape = ZonikShapes.cardShape,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)
    ) {
        Column(content = content)
    }
}

@Composable
private fun GroupDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 72.dp),
        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f)
    )
}

@Composable
private fun SettingIcon(painter: Painter) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.size(40.dp)
    ) {
        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
            Icon(painter, contentDescription = null, modifier = Modifier.size(22.dp))
        }
    }
}

/** One settings row. The whole row is the touch target when [onClick] is set. */
@Composable
private fun SettingRow(
    title: String,
    summary: String? = null,
    icon: ImageVector? = null,
    painter: Painter? = null,
    enabled: Boolean = true,
    titleColor: Color? = null,
    summaryColor: Color? = null,
    onClick: (() -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    val iconPainter = painter ?: icon?.let { rememberVectorPainter(it) }
    ListItem(
        modifier = Modifier
            .then(if (onClick != null) Modifier.clickable(enabled = enabled, onClick = onClick) else Modifier)
            .alpha(if (enabled) 1f else 0.5f),
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        headlineContent = {
            Text(title, color = titleColor ?: Color.Unspecified)
        },
        supportingContent = summary?.let {
            { Text(it, color = summaryColor ?: MaterialTheme.colorScheme.onSurfaceVariant) }
        },
        leadingContent = iconPainter?.let { { SettingIcon(it) } },
        trailingContent = trailing
    )
}

/** A row with a switch; tapping anywhere on the row flips it. */
@Composable
private fun SwitchRow(
    title: String,
    summary: String?,
    icon: ImageVector,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    enabled: Boolean = true,
) {
    ListItem(
        modifier = Modifier
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onCheckedChange)
            .alpha(if (enabled) 1f else 0.5f),
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        headlineContent = { Text(title) },
        supportingContent = summary?.let {
            { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        },
        leadingContent = { SettingIcon(rememberVectorPainter(icon)) },
        trailingContent = { Switch(checked = checked, onCheckedChange = null, enabled = enabled) }
    )
}

/**
 * A row that shows its current choice and opens a single-choice dialog when tapped.
 * [hint] is an optional second line explaining the setting.
 */
@Composable
private fun <T> ChoiceRow(
    title: String,
    icon: ImageVector,
    options: List<Pair<T, String>>,
    selected: T,
    onSelect: (T) -> Unit,
    hint: String? = null,
    enabled: Boolean = true,
) {
    var open by remember { mutableStateOf(false) }
    val current = options.firstOrNull { it.first == selected }?.second ?: selected.toString()

    ListItem(
        modifier = Modifier
            .clickable(enabled = enabled) { open = true }
            .alpha(if (enabled) 1f else 0.5f),
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        headlineContent = { Text(title) },
        supportingContent = {
            Column {
                Text(current, color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Medium)
                if (hint != null) {
                    Text(hint, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
        leadingContent = { SettingIcon(rememberVectorPainter(icon)) },
        trailingContent = { Chevron() }
    )

    if (open) {
        AlertDialog(
            onDismissRequest = { open = false },
            title = { Text(title) },
            text = {
                Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                    options.forEach { (value, label) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(8.dp))
                                .selectable(
                                    selected = value == selected,
                                    role = Role.RadioButton,
                                    onClick = { onSelect(value); open = false }
                                )
                                .padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            RadioButton(selected = value == selected, onClick = null)
                            Spacer(modifier = Modifier.width(12.dp))
                            Text(label, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { open = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun UsageBar(used: Long, limitBytes: Long) {
    val fraction = (used.toFloat() / limitBytes.toFloat()).coerceIn(0f, 1f)
    LinearProgressIndicator(
        progress = { fraction },
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 72.dp, end = 16.dp, bottom = 12.dp)
            .height(4.dp)
            .clip(RoundedCornerShape(2.dp)),
        color = if (fraction > 0.9f) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
        trackColor = MaterialTheme.colorScheme.surfaceVariant
    )
}

@Composable
private fun Chevron() {
    Icon(
        Icons.Default.ChevronRight,
        contentDescription = null,
        tint = MaterialTheme.colorScheme.onSurfaceVariant
    )
}

@Composable
private fun EditHint() {
    Icon(
        Icons.Default.Edit,
        contentDescription = null,
        modifier = Modifier.size(18.dp),
        tint = MaterialTheme.colorScheme.onSurfaceVariant
    )
}

@Composable
private fun StatItem(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = value,
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )
        Text(
            text = label.uppercase(),
            style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 1.sp),
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

private fun mbLabel(mb: Int): String = if (mb < 1024) "$mb MB" else "${mb / 1024} GB"

// endregion
