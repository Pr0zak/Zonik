package com.zonik.app.ui.screens.search

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.zonik.app.data.DebugLog
import com.zonik.app.data.DownloadNotice
import com.zonik.app.data.DownloadNotifier
import com.zonik.app.data.api.*
import com.zonik.app.data.db.ZonikDatabase
import com.zonik.app.data.repository.LibraryRepository
import com.zonik.app.media.PlaybackManager
import com.zonik.core.model.Album
import com.zonik.core.model.Artist
import com.zonik.core.model.Track
import com.zonik.app.ui.components.CoverArt
import com.zonik.app.ui.theme.WithNeutralScheme
import com.zonik.app.ui.util.formatDuration
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

// region State

enum class GetState { Idle, Searching, Downloading, Done, Failed }

data class GetButtonState(
    val state: GetState = GetState.Idle,
    val jobId: String? = null,
    val pct: Float = 0f,
    val received: Long = 0L,
    val total: Long = 0L,
    val error: String? = null,
    /** Short button label while working ("Finding", "Waiting", "Adding"). */
    val label: String = "Queued",
    /** One line under the row saying what's happening right now. */
    val detail: String? = null,
    /** Library track to play once done. */
    val trackId: String? = null,
    val speedBps: Long = 0L,
    val etaSeconds: Long? = null,
    /** Peers that failed this job, skipped by "Try another source". */
    val failedSources: List<String> = emptyList()
) {
    val inFlight: Boolean get() = state == GetState.Searching || state == GetState.Downloading
}

/**
 * Something you pressed Get on: a catalog song (the server picks the file) or
 * a specific file from the network list.
 */
data class DownloadRow(
    val artist: String,
    val track: String,
    val catalog: CatalogTrack? = null,
    val file: DownloadResult? = null
) {
    val title: String get() = catalog?.title ?: file?.displayName ?: track
}

data class SearchUiState(
    val query: String = "",
    val artists: List<Artist> = emptyList(),
    val albums: List<Album> = emptyList(),
    val tracks: List<Track> = emptyList(),
    val isLibrarySearching: Boolean = false,
    val hasSearched: Boolean = false,
    val libraryError: String? = null,
    val downloadResults: List<DownloadResult> = emptyList(),
    val isDownloadSearching: Boolean = false,
    val hasDownloadSearched: Boolean = false,
    val downloadError: String? = null,
    val parsedArtist: String = "",
    val parsedTrack: String = "",
    /** The network search's song is already in the library (server-matched). */
    val libraryMatchId: String? = null,
    val activeTransfers: List<TransferInfo> = emptyList(),
    val activeJobs: List<JobInfo> = emptyList(),
    val recentJobs: List<JobInfo> = emptyList(),
    val getStates: Map<String, GetButtonState> = emptyMap(),
    /** Rows you pressed Get on, kept across query changes until cleared. */
    val pinned: Map<String, DownloadRow> = emptyMap(),
    /** Catalog (Deezer/Last.fm) matches for the query, owned or not. */
    val catalog: List<CatalogTrack> = emptyList(),
    val isCatalogSearching: Boolean = false,
    val hasCatalogSearched: Boolean = false,
    val catalogError: String? = null,
    /** AI suggestions: songs the query might describe. null = not asked. */
    val aiTracks: List<CatalogTrack>? = null,
    val isAiSearching: Boolean = false,
    val aiAvailable: Boolean = false,
    val progress: Map<String, JobProgress> = emptyMap(),
    /** Set when the download status couldn't be refreshed. */
    val statusError: String? = null,
    val soulseekOnline: Boolean = true,
    val toast: String? = null
)

// endregion

// region ViewModel

@OptIn(FlowPreview::class)
@HiltViewModel
class SearchViewModel @Inject constructor(
    private val libraryRepository: LibraryRepository,
    private val playbackManager: PlaybackManager,
    private val zonikApi: ZonikApi,
    private val database: ZonikDatabase,
    private val progressClient: DownloadProgressClient,
    private val notifier: DownloadNotifier
) : ViewModel() {

    companion object {
        private const val TAG = "SearchVM"
        // A row whose job hasn't been heard from over the WebSocket for this long
        // is refreshed over REST instead.
        private const val WS_STALE_MS = 15_000L
    }

    private val _query = MutableStateFlow("")
    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState: StateFlow<SearchUiState> = _uiState.asStateFlow()

    private var librarySearchJob: Job? = null
    private var downloadSearchJob: Job? = null
    private var catalogSearchJob: Job? = null
    private var statusPollJob: Job? = null
    // "Choose source…" sets the query and starts a network search at once; the
    // debounced library search that follows must not wipe those results.
    private var keepNetworkForQuery: String? = null

    init {
        // Library search reacts to debounced query changes
        _query
            .debounce(300)
            .distinctUntilChanged()
            .onEach { q ->
                if (q.isBlank()) {
                    _uiState.update {
                        it.copy(
                            artists = emptyList(),
                            albums = emptyList(),
                            tracks = emptyList(),
                            isLibrarySearching = false,
                            hasSearched = false,
                            libraryError = null,
                            downloadResults = emptyList(),
                            isDownloadSearching = false,
                            hasDownloadSearched = false,
                            downloadError = null,
                            parsedArtist = "",
                            parsedTrack = "",
                            libraryMatchId = null,
                            catalog = emptyList(),
                            isCatalogSearching = false,
                            hasCatalogSearched = false,
                            catalogError = null,
                            aiTracks = null,
                            isAiSearching = false
                        )
                    }
                } else {
                    runLibrarySearch(q, keepNetwork = q == keepNetworkForQuery)
                    keepNetworkForQuery = null
                    runCatalogSearch(q)
                }
            }
            .launchIn(viewModelScope)

        // Mirror progress map into UI state and resolve get-button states
        progressClient.progress
            .onEach { progressMap ->
                val finished = mutableListOf<String>()
                _uiState.update { state ->
                    val updatedGetStates = state.getStates.mapValues { (key, gs) ->
                        val jp = gs.jobId?.let { progressMap[it] } ?: return@mapValues gs
                        val next = gs.resolve(jp)
                        if (next.state == GetState.Done && gs.state != GetState.Done) finished += key
                        next
                    }
                    state.copy(progress = progressMap, getStates = updatedGetStates)
                }
                publishNotifications()
                if (finished.isNotEmpty()) onDownloadsFinished(finished)
            }
            .launchIn(viewModelScope)

        // Initial load of active downloads + recent history
        viewModelScope.launch {
            progressClient.acquire()
            refreshStatus()
            loadRecentHistory()
        }
        startStatusPolling()
    }

    override fun onCleared() {
        super.onCleared()
        viewModelScope.launch { progressClient.release() }
    }

    fun onQueryChanged(newQuery: String) {
        _uiState.update { it.copy(query = newQuery) }
        _query.value = newQuery
    }

    fun playTrack(track: Track) = playbackManager.playTracks(listOf(track), 0)
    fun playNext(track: Track) = playbackManager.playNext(track)
    fun addToQueue(track: Track) = playbackManager.addToQueue(track)

    fun toggleMarkForDeletion(track: Track) {
        viewModelScope.launch {
            if (track.markedForDeletion) {
                libraryRepository.unmarkForDeletion(track.id)
            } else {
                libraryRepository.markForDeletion(track.id)
            }
            _uiState.update { state ->
                state.copy(
                    tracks = state.tracks.map {
                        if (it.id == track.id) it.copy(markedForDeletion = !track.markedForDeletion) else it
                    }
                )
            }
        }
    }

    fun startRadio(track: Track) {
        viewModelScope.launch {
            try {
                val radioTracks = libraryRepository.startRadio(track.id, track.genre, track.artistId)
                if (radioTracks.isNotEmpty()) playbackManager.playTracks(radioTracks)
                else _uiState.update { it.copy(toast = "No radio tracks found for this song") }
            } catch (e: Exception) {
                DebugLog.w(TAG, "Radio failed: ${e.message}")
                _uiState.update { it.copy(toast = "Couldn't start radio: ${friendlyError(e)}") }
            }
        }
    }

    /** Play a library track by id — a finished download, or the copy already there. */
    fun playTrackId(trackId: String) {
        viewModelScope.launch {
            try {
                val track = libraryRepository.fetchTrack(trackId)
                if (track != null) playbackManager.playTracks(listOf(track), 0)
                else _uiState.update { it.copy(toast = "That track isn't in the library any more") }
            } catch (e: Exception) {
                DebugLog.e(TAG, "Play $trackId failed", e)
                _uiState.update { it.copy(toast = "Couldn't play it: ${friendlyError(e)}") }
            }
        }
    }

    fun searchOnline(force: Boolean = false) {
        val query = _uiState.value.query.trim()
        if (query.isBlank()) return
        if (!force && _uiState.value.isDownloadSearching) return
        runDownloadSearch(query)
    }

    /** Get a specific file from the network list. */
    fun triggerDownload(result: DownloadResult) {
        val parsed = parseQuery(_uiState.value.query)
        val artist = parsed.first.ifBlank { _uiState.value.parsedArtist }
        val track = parsed.second.ifBlank { _uiState.value.parsedTrack }
            .ifBlank { result.displayName }
        startDownload(result.key(), DownloadRow(artist, track, file = result), result.username, result.filename)
    }

    /** Get a catalog song — the server finds and picks the best source. */
    fun getCatalogTrack(track: CatalogTrack) {
        startDownload(track.key, DownloadRow(track.artist, track.title, catalog = track))
    }

    /**
     * After a failure: let the server pick again, skipping every peer that has
     * failed this song so far (and the picked file's peer, for a file row).
     */
    fun tryAnotherSource(key: String) {
        val state = _uiState.value
        val row = state.pinned[key] ?: return
        val gs = state.getStates[key]
        val exclude = ((gs?.failedSources ?: emptyList()) + listOfNotNull(row.file?.username)).distinct()
        startDownload(key, row, excludeUsers = exclude)
    }

    /** Show the raw network file list for a catalog song. */
    fun chooseSources(track: CatalogTrack) {
        val q = "${track.artist} - ${track.title}"
        keepNetworkForQuery = q
        onQueryChanged(q)
        runDownloadSearch(q)
    }

    private fun startDownload(
        key: String,
        row: DownloadRow,
        username: String? = null,
        filename: String? = null,
        excludeUsers: List<String> = emptyList()
    ) {
        notifier.reset(key)
        viewModelScope.launch {
            _uiState.update { state ->
                val carried = state.getStates[key]?.failedSources ?: emptyList()
                state.copy(
                    getStates = state.getStates + (key to GetButtonState(
                        state = GetState.Searching, label = "Starting", failedSources = carried
                    )),
                    pinned = state.pinned + (key to row)
                )
            }
            try {
                DebugLog.d(TAG, "Trigger artist='${row.artist}' track='${row.track}' user=$username exclude=$excludeUsers")
                val response = zonikApi.triggerDownload(
                    DownloadTriggerRequest(
                        artist = row.artist,
                        track = row.track,
                        username = username,
                        filename = filename,
                        excludeUsers = excludeUsers
                    )
                )
                val jobId = response.jobId
                when {
                    response.error != null -> setRowFailed(
                        key,
                        if (response.error == "blacklisted") "Blocked by your download blacklist" +
                            (response.reason?.let { ": $it" } ?: "")
                        else response.error
                    )
                    response.status == "in_library" && response.trackId != null -> {
                        _uiState.update { state ->
                            state.copy(getStates = state.getStates + (key to GetButtonState(
                                state = GetState.Done, trackId = response.trackId, pct = 100f,
                                detail = "Already in your library"
                            )))
                        }
                        publishNotifications()
                    }
                    jobId == null -> setRowFailed(key, "The server didn't start the download")
                    else -> {
                        _uiState.update { state ->
                            val gs = state.getStates[key] ?: GetButtonState()
                            state.copy(
                                getStates = state.getStates + (key to gs.copy(
                                    jobId = jobId, state = GetState.Searching, label = "Queued",
                                    detail = if (response.status == "already_downloading") "Already being downloaded" else null
                                ))
                            )
                        }
                        // Seed the job so the WebSocket loop connects straight away
                        // instead of waiting for the next status poll.
                        if (progressClient.progress.value[jobId] == null) {
                            progressClient.setJobStatus(jobId, "running")
                        }
                        refreshStatus()
                    }
                }
            } catch (e: Exception) {
                DebugLog.e(TAG, "Trigger failed", e)
                setRowFailed(key, friendlyError(e))
            }
        }
    }

    private fun setRowFailed(key: String, error: String) {
        _uiState.update { state ->
            val gs = state.getStates[key] ?: GetButtonState()
            state.copy(getStates = state.getStates + (key to gs.copy(state = GetState.Failed, error = error)))
        }
        publishNotifications()
    }

    /** Drop finished and failed rows from "Your downloads". */
    fun clearFinished() {
        _uiState.update { state ->
            val keep = state.pinned.filterKeys { state.getStates[it]?.inFlight == true }
            state.copy(pinned = keep, getStates = state.getStates.filterKeys { it in keep })
        }
        progressClient.clearTerminal()
    }

    fun cancelTransfer(transfer: TransferInfo) {
        viewModelScope.launch {
            try {
                zonikApi.cancelTransfer(
                    CancelTransferRequest(username = transfer.username, filename = transfer.filename)
                )
                refreshStatus()
            } catch (e: Exception) {
                DebugLog.e(TAG, "Cancel failed", e)
                _uiState.update { it.copy(toast = "Couldn't cancel: ${friendlyError(e)}") }
            }
        }
    }

    fun refreshStatus() {
        viewModelScope.launch {
            try {
                val statusResponse = zonikApi.getDownloadStatus()
                val activeJobs = zonikApi.getActiveJobs()
                _uiState.update {
                    it.copy(
                        activeTransfers = statusResponse.transfers,
                        activeJobs = activeJobs,
                        soulseekOnline = statusResponse.loggedIn,
                        statusError = null
                    )
                }
                progressClient.applyTransfers(statusResponse.transfers)
                // Drive the WS connect loop off real server state — it only
                // connects while there's active work to watch.
                progressClient.setServerReportsActive(
                    statusResponse.transfers.isNotEmpty() || activeJobs.isNotEmpty()
                )
                refreshStaleRows(activeJobs.map { it.id }.toSet())
            } catch (e: Exception) {
                DebugLog.w(TAG, "Status refresh failed: ${e.message}")
                _uiState.update { it.copy(statusError = "Couldn't refresh downloads: ${friendlyError(e)}") }
            }
        }
    }

    /**
     * REST fallback for rows the WebSocket hasn't updated lately — including
     * jobs that already finished (they drop out of the active list), so a row
     * never sits on "Queued" after the download is done.
     */
    private suspend fun refreshStaleRows(activeIds: Set<String>) {
        val now = System.currentTimeMillis()
        val progress = progressClient.progress.value
        val stale = _uiState.value.getStates.values
            .filter { it.inFlight && it.jobId != null }
            .mapNotNull { it.jobId }
            .filter { id ->
                val p = progress[id]
                id !in activeIds || !progressClient.connected.value || p == null || now - p.updatedAt > WS_STALE_MS
            }
        for (id in stale) {
            try {
                progressClient.applyJobSnapshot(zonikApi.getJob(id))
            } catch (e: Exception) {
                DebugLog.w(TAG, "Job $id refresh failed: ${e.message}")
            }
        }
    }

    fun loadRecentHistory() {
        viewModelScope.launch {
            try {
                val response = zonikApi.getJobHistory(limit = 20)
                _uiState.update { it.copy(recentJobs = response.items) }
            } catch (e: Exception) {
                DebugLog.w(TAG, "History load failed: ${e.message}")
                _uiState.update { it.copy(toast = "Couldn't load recent downloads: ${friendlyError(e)}") }
            }
        }
    }

    fun dismissToast() {
        _uiState.update { it.copy(toast = null) }
    }

    private fun onDownloadsFinished(keys: List<String>) {
        val state = _uiState.value
        val names = keys.mapNotNull { state.pinned[it]?.title }
        if (names.isNotEmpty()) {
            _uiState.update {
                it.copy(toast = if (names.size == 1) "Ready: ${names[0]}" else "${names.size} downloads ready")
            }
        }
        // The new tracks are in the library now: re-run the search so they show
        // up there, and pull them into the local DB for Auto/Watch.
        if (state.query.isNotBlank()) {
            runLibrarySearch(state.query, keepNetwork = true)
            runCatalogSearch(state.query)
        }
        viewModelScope.launch {
            for (key in keys) {
                val trackId = _uiState.value.getStates[key]?.trackId ?: continue
                try { libraryRepository.fetchTrack(trackId) } catch (e: Exception) {
                    DebugLog.w(TAG, "Couldn't cache new track $trackId: ${e.message}")
                }
            }
        }
        loadRecentHistory()
        refreshStatus()
    }

    private fun publishNotifications() {
        val state = _uiState.value
        notifier.update(state.pinned.mapNotNull { (key, row) ->
            val gs = state.getStates[key] ?: return@mapNotNull null
            DownloadNotice(
                key = key,
                title = row.title,
                active = gs.inFlight,
                done = gs.state == GetState.Done,
                failed = gs.state == GetState.Failed,
                pct = gs.pct.toInt(),
                detail = if (gs.state == GetState.Failed) gs.error else gs.detail
            )
        })
    }

    private fun runLibrarySearch(query: String, keepNetwork: Boolean = false) {
        librarySearchJob?.cancel()
        // Clear download results when query changes (rows you pressed Get on
        // stay, under "Your downloads")
        if (!keepNetwork) {
            _uiState.update {
                it.copy(
                    downloadResults = emptyList(),
                    hasDownloadSearched = false,
                    downloadError = null,
                    libraryMatchId = null
                )
            }
        }
        librarySearchJob = viewModelScope.launch {
            _uiState.update { it.copy(isLibrarySearching = true, libraryError = null) }
            try {
                val (artists, albums, tracks) = libraryRepository.search(query)
                _uiState.update {
                    it.copy(
                        artists = artists,
                        albums = albums,
                        tracks = tracks,
                        isLibrarySearching = false,
                        hasSearched = true
                    )
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                DebugLog.w(TAG, "Library search failed: ${e.message}")
                _uiState.update {
                    it.copy(
                        isLibrarySearching = false,
                        hasSearched = true,
                        libraryError = friendlyError(e)
                    )
                }
            }
        }
    }

    private fun runCatalogSearch(query: String) {
        catalogSearchJob?.cancel()
        if (query.trim().length < 2) return
        catalogSearchJob = viewModelScope.launch {
            _uiState.update { it.copy(isCatalogSearching = true, catalogError = null, aiTracks = null, isAiSearching = false) }
            try {
                val response = zonikApi.searchCatalog(query.trim())
                _uiState.update { state ->
                    // A song someone is already downloading (here or on the web)
                    // shows its live status instead of a Get button.
                    val adopted = (response.tracks + response.aiTracks.orEmpty())
                        .filter { it.jobId != null && state.getStates[it.key]?.jobId == null }
                        .associate { it.key to GetButtonState(state = GetState.Searching, jobId = it.jobId, label = "Queued") }
                    state.copy(
                        catalog = response.tracks,
                        isCatalogSearching = false,
                        hasCatalogSearched = true,
                        catalogError = response.error,
                        aiTracks = response.aiTracks,
                        aiAvailable = response.aiAvailable,
                        getStates = state.getStates + adopted
                    )
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                DebugLog.w(TAG, "Catalog search failed: ${e.message}")
                _uiState.update {
                    it.copy(isCatalogSearching = false, hasCatalogSearched = true, catalogError = friendlyError(e))
                }
            }
        }
    }

    /** Ask the server's AI which songs the query describes. */
    fun askAi() {
        val query = _uiState.value.query.trim()
        if (query.length < 2 || _uiState.value.isAiSearching) return
        viewModelScope.launch {
            _uiState.update { it.copy(isAiSearching = true) }
            try {
                val response = zonikApi.searchCatalog(query, limit = 10, ai = true)
                // Drop the answer if the query changed while the AI was thinking.
                if (_uiState.value.query.trim() != query) return@launch
                _uiState.update {
                    it.copy(isAiSearching = false, aiTracks = response.aiTracks.orEmpty())
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                DebugLog.w(TAG, "AI search failed: ${e.message}")
                _uiState.update { it.copy(isAiSearching = false, toast = "AI search failed: ${friendlyError(e)}") }
            } finally {
                _uiState.update { it.copy(isAiSearching = false) }
            }
        }
    }

    private fun runDownloadSearch(query: String) {
        downloadSearchJob?.cancel()
        val (artist, track) = parseQuery(query)
        downloadSearchJob = viewModelScope.launch {
            _uiState.update {
                it.copy(
                    isDownloadSearching = true,
                    downloadError = null,
                    parsedArtist = artist,
                    parsedTrack = track
                )
            }
            try {
                val request = if (artist.isNotBlank()) {
                    DownloadSearchRequest(artist = artist, track = track)
                } else {
                    DownloadSearchRequest(query = track)
                }
                val response = zonikApi.searchDownloads(request)
                val sorted = response.results.sortedWith(downloadResultComparator())
                _uiState.update {
                    it.copy(
                        downloadResults = sorted,
                        isDownloadSearching = false,
                        hasDownloadSearched = true,
                        libraryMatchId = response.libraryTrackId,
                        downloadError = if (response.blacklisted)
                            "Blocked by your download blacklist" + (response.reason?.let { r -> ": $r" } ?: "")
                        else null
                    )
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                DebugLog.w(TAG, "Network search failed: ${e.message}")
                _uiState.update {
                    it.copy(
                        isDownloadSearching = false,
                        hasDownloadSearched = true,
                        downloadError = friendlyError(e)
                    )
                }
            }
        }
    }

    private fun startStatusPolling() {
        statusPollJob?.cancel()
        statusPollJob = viewModelScope.launch {
            while (true) {
                delay(8_000)
                val state = _uiState.value
                val hasActive = state.activeTransfers.isNotEmpty() || state.activeJobs.isNotEmpty() ||
                    state.getStates.values.any { it.inFlight && it.jobId != null }
                if (hasActive) {
                    refreshStatus()
                } else {
                    // Nothing active in our last view — make sure the WS connect
                    // loop's server-side hint is cleared so it idles instead of
                    // reconnecting forever.
                    progressClient.setServerReportsActive(false)
                }
            }
        }
    }
}

/** Where a download is, in words, from the server's job + transfer state. */
internal fun GetButtonState.resolve(jp: JobProgress): GetButtonState {
    val base = copy(
        pct = jp.pct, received = jp.progress, total = jp.total,
        speedBps = jp.speedBps, etaSeconds = jp.etaSeconds,
        trackId = jp.trackId ?: trackId,
        failedSources = jp.failedSources.ifEmpty { failedSources }
    )
    return when (jp.status.lowercase()) {
        "completed", "complete" -> base.copy(
            state = GetState.Done, pct = 100f, error = null,
            detail = if (jp.alreadyInLibrary) "Already in your library" else "Added to your library"
        )
        "failed", "error", "cancelled" -> base.copy(
            state = GetState.Failed, error = jp.error ?: "The download failed"
        )
        "pending" -> base.copy(state = GetState.Searching, label = "Queued", detail = "Waiting for a free download slot")
        else -> when (jp.transferState?.lowercase()) {
            "transferring" -> base.copy(
                state = GetState.Downloading,
                detail = listOfNotNull(
                    jp.speedBps.takeIf { it > 0 }?.let { "%.1f MB/s".format(it / 1_048_576.0) },
                    jp.etaSeconds?.takeIf { it > 0 }?.let { formatEta(it) }
                ).joinToString(" · ").ifBlank { null }
            )
            "requested", "queued", "connected" -> base.copy(
                state = GetState.Searching, label = "Waiting", detail = "Waiting for the peer to start sending"
            )
            "completed" -> base.copy(state = GetState.Searching, label = "Adding", detail = "Adding to your library")
            "failed", "denied" -> base.copy(
                state = GetState.Searching, label = "Retrying", detail = "That source failed — trying another"
            )
            else -> base.copy(state = GetState.Searching, label = "Finding", detail = "Finding a source")
        }
    }
}

internal fun formatEta(seconds: Long): String =
    if (seconds < 60) "${seconds}s left" else "${seconds / 60}m ${seconds % 60}s left"

// endregion

// region Helpers

internal fun DownloadResult.key(): String = "${username}|${filename}"

internal fun parseQuery(raw: String): Pair<String, String> {
    val trimmed = raw.trim()
    if (trimmed.isBlank()) return "" to ""
    // Split on " - " (with surrounding whitespace) — common artist/track separator
    val sep = Regex("\\s+[-—–]\\s+")
    val parts = trimmed.split(sep, limit = 2)
    return if (parts.size == 2 && parts[0].isNotBlank() && parts[1].isNotBlank()) {
        parts[0].trim() to parts[1].trim()
    } else {
        "" to trimmed
    }
}

private fun formatPriority(format: String): Int = when (format.uppercase()) {
    "FLAC" -> 0
    "MP3", "M4A", "AAC", "OGG" -> 1
    "WAV" -> 2
    else -> 3
}

private fun downloadResultComparator(): Comparator<DownloadResult> {
    return Comparator { a, b ->
        // Format priority
        val fp = formatPriority(a.format).compareTo(formatPriority(b.format))
        if (fp != 0) return@Comparator fp
        // For MP3-class, prefer >= 320kbps
        val aHigh = (a.bitRate ?: 0) >= 320
        val bHigh = (b.bitRate ?: 0) >= 320
        if (aHigh != bHigh) return@Comparator if (aHigh) -1 else 1
        // Slots free
        val aSlot = a.slotsFree == true || (a.freeUploadSlots ?: 0) > 0
        val bSlot = b.slotsFree == true || (b.freeUploadSlots ?: 0) > 0
        if (aSlot != bSlot) return@Comparator if (aSlot) -1 else 1
        // Bitrate descending
        val br = (b.bitRate ?: 0).compareTo(a.bitRate ?: 0)
        if (br != 0) return@Comparator br
        // File size descending
        b.size.compareTo(a.size)
    }
}

internal fun formatBytes(bytes: Long): String {
    if (bytes <= 0) return "0 B"
    val units = arrayOf("B", "KB", "MB", "GB")
    var v = bytes.toDouble()
    var i = 0
    while (v >= 1024 && i < units.lastIndex) {
        v /= 1024.0
        i++
    }
    return "%.1f %s".format(v, units[i])
}

// endregion

// region Screen

private enum class SearchFilter { ALL, ALBUMS, ARTISTS, TRACKS }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(
    onNavigateToArtist: (String) -> Unit,
    onNavigateToAlbum: (String) -> Unit,
    viewModel: SearchViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var filter by remember { mutableStateOf(SearchFilter.ALL) }
    var recentExpanded by rememberSaveable { mutableStateOf(false) }
    var catalogExpanded by rememberSaveable(uiState.query) { mutableStateOf(false) }

    LaunchedEffect(uiState.toast) {
        if (uiState.toast != null) {
            delay(3_000)
            viewModel.dismissToast()
        }
    }

    WithNeutralScheme {
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.surface
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .statusBarsPadding()
                ) {
                    M3SearchBar(
                        query = uiState.query,
                        onQueryChange = viewModel::onQueryChanged
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    if (uiState.query.isNotBlank()) {
                        FilterChipRow(selected = filter, onSelect = { filter = it })
                        Spacer(modifier = Modifier.height(8.dp))
                    }

                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(bottom = 200.dp)
                    ) {
                        item("status-banners") {
                            StatusBanners(state = uiState)
                        }
                        yourDownloadsSection(
                            state = uiState,
                            onPlay = viewModel::playTrackId,
                            onRetry = viewModel::tryAnotherSource,
                            onClearFinished = viewModel::clearFinished
                        )
                        if (uiState.query.isBlank()) {
                            // Empty state — show active downloads summary + recents
                            item("active") {
                                ActiveDownloadsSection(
                                    transfers = uiState.activeTransfers,
                                    activeJobs = uiState.activeJobs,
                                    progress = uiState.progress,
                                    onCancel = viewModel::cancelTransfer
                                )
                            }
                            item("recents") {
                                RecentDownloadsSection(
                                    expanded = recentExpanded,
                                    onToggle = { recentExpanded = !recentExpanded },
                                    recents = uiState.recentJobs,
                                    onRefresh = viewModel::loadRecentHistory,
                                    onPlay = viewModel::playTrackId
                                )
                            }
                            item("emptyHint") {
                                EmptyHint()
                            }
                        } else {
                            // Library results section
                            librarySection(
                                query = uiState.query,
                                filter = filter,
                                state = uiState,
                                onArtistClick = { onNavigateToArtist(it.id) },
                                onAlbumClick = { onNavigateToAlbum(it.id) },
                                onTrackClick = { viewModel.playTrack(it) },
                                onPlayNext = { viewModel.playNext(it) },
                                onAddToQueue = { viewModel.addToQueue(it) },
                                onToggleMarkForDeletion = { viewModel.toggleMarkForDeletion(it) },
                                onStartRadio = { viewModel.startRadio(it) }
                            )

                            catalogSection(
                                state = uiState,
                                expanded = catalogExpanded,
                                onToggleExpanded = { catalogExpanded = !catalogExpanded },
                                onGet = viewModel::getCatalogTrack,
                                onPlay = viewModel::playTrackId,
                                onChooseSource = viewModel::chooseSources,
                                onAskAi = viewModel::askAi
                            )

                            // Raw network file list
                            getMoreSection(
                                state = uiState,
                                onSearchOnline = { viewModel.searchOnline() },
                                onTrigger = { viewModel.triggerDownload(it) },
                                onPlay = viewModel::playTrackId
                            )

                            item("activeFooter") {
                                if (uiState.activeTransfers.isNotEmpty() || uiState.activeJobs.isNotEmpty()) {
                                    Spacer(modifier = Modifier.height(16.dp))
                                    SectionHeader("In progress")
                                    ActiveTransfersList(
                                        transfers = uiState.activeTransfers,
                                        progress = uiState.progress,
                                        onCancel = viewModel::cancelTransfer
                                    )
                                }
                            }
                        }
                    }
                }

                if (uiState.toast != null) {
                    Snackbar(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .padding(16.dp),
                        action = {
                            TextButton(onClick = viewModel::dismissToast) { Text("Dismiss") }
                        }
                    ) {
                        Text(uiState.toast!!)
                    }
                }
            }
        }
    }
}

// endregion

// region Library section

private fun androidx.compose.foundation.lazy.LazyListScope.librarySection(
    query: String,
    filter: SearchFilter,
    state: SearchUiState,
    onArtistClick: (Artist) -> Unit,
    onAlbumClick: (Album) -> Unit,
    onTrackClick: (Track) -> Unit,
    onPlayNext: (Track) -> Unit,
    onAddToQueue: (Track) -> Unit,
    onToggleMarkForDeletion: (Track) -> Unit,
    onStartRadio: (Track) -> Unit
) {
    if (state.libraryError != null) {
        item("libraryError") {
            ErrorBanner(text = state.libraryError)
        }
        return
    }

    if (state.isLibrarySearching && !state.hasSearched) {
        item("libraryLoading") {
            Box(
                modifier = Modifier.fillMaxWidth().padding(32.dp),
                contentAlignment = Alignment.Center
            ) { CircularProgressIndicator() }
        }
        return
    }

    val showArtists = filter == SearchFilter.ALL || filter == SearchFilter.ARTISTS
    val showAlbums = filter == SearchFilter.ALL || filter == SearchFilter.ALBUMS
    val showTracks = filter == SearchFilter.ALL || filter == SearchFilter.TRACKS

    val anyResults = state.artists.isNotEmpty() || state.albums.isNotEmpty() || state.tracks.isNotEmpty()

    if (anyResults) {
        item("library-h") {
            SectionHeader("In your library")
        }

        if (filter == SearchFilter.ALL) {
            val topAlbum = state.albums.firstOrNull()
            if (topAlbum != null) {
                item("top") {
                    TopResultHero(
                        query = query,
                        album = topAlbum,
                        onClick = { onAlbumClick(topAlbum) }
                    )
                }
            }
        }

        if (showArtists && state.artists.isNotEmpty()) {
            item("artists-h") { SubHeader("Artists") }
            items(state.artists, key = { "artist-${it.id}" }) { artist ->
                ResultRow(
                    kind = "Artist",
                    headline = artist.name,
                    sub = "${artist.albumCount} album${if (artist.albumCount != 1) "s" else ""}",
                    coverArtId = artist.coverArt,
                    query = query,
                    onClick = { onArtistClick(artist) }
                )
            }
        }

        if (showAlbums && state.albums.isNotEmpty()) {
            item("albums-h") { SubHeader("Albums") }
            items(state.albums, key = { "album-${it.id}" }) { album ->
                ResultRow(
                    kind = "Album",
                    headline = album.name,
                    sub = album.artist,
                    coverArtId = album.coverArt,
                    query = query,
                    onClick = { onAlbumClick(album) }
                )
            }
        }

        if (showTracks && state.tracks.isNotEmpty()) {
            item("tracks-h") { SubHeader("Tracks") }
            itemsIndexed(state.tracks, key = { _, track -> "track-${track.id}" }) { _, track ->
                TrackRow(
                    track = track,
                    query = query,
                    onClick = { onTrackClick(track) },
                    onPlayNext = { onPlayNext(track) },
                    onAddToQueue = { onAddToQueue(track) },
                    onToggleMarkForDeletion = { onToggleMarkForDeletion(track) },
                    onStartRadio = { onStartRadio(track) }
                )
            }
        }
    } else if (state.hasSearched) {
        item("library-empty") {
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerLow,
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp)
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(12.dp)
                ) {
                    Icon(
                        Icons.Default.LibraryMusic,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = "Nothing in your library matches \"$query\"",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

// endregion

// region Catalog section

private const val CATALOG_COLLAPSED = 8

private fun androidx.compose.foundation.lazy.LazyListScope.catalogSection(
    state: SearchUiState,
    expanded: Boolean,
    onToggleExpanded: () -> Unit,
    onGet: (CatalogTrack) -> Unit,
    onPlay: (String) -> Unit,
    onChooseSource: (CatalogTrack) -> Unit,
    onAskAi: () -> Unit
) {
    if (state.query.isBlank()) return
    val libraryIds = state.tracks.map { it.id }.toSet()
    // Owned songs the library search missed (a typo, "feat." naming) — the
    // catalog's fuzzy match found them, so offer Play here.
    val closeOwned = state.catalog.filter { it.inLibrary && it.trackId != null && it.trackId !in libraryIds }
    val missing = state.catalog.filter { !it.inLibrary && it.key !in state.pinned }
    if (!state.isCatalogSearching && !state.hasCatalogSearched) return

    item("catalog-h") {
        Spacer(modifier = Modifier.height(16.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 4.dp)
        ) {
            Text(
                text = "Not in your library",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.weight(1f)
            )
            if (state.isCatalogSearching) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
            }
        }
    }
    state.catalogError?.let { err -> item("catalog-err") { ErrorBanner(text = err) } }

    if (closeOwned.isNotEmpty()) {
        item("catalog-owned-h") { SubHeader("Did you mean") }
        items(closeOwned, key = { "cat-owned-${it.key}" }) { t ->
            CatalogTrackRow(t, GetButtonState(), onGet = {}, onPlay = onPlay, onChooseSource = null)
        }
    }

    if (state.hasCatalogSearched && missing.isEmpty() && closeOwned.isEmpty() && state.catalogError == null) {
        item("catalog-empty") {
            Text(
                text = if (state.catalog.isEmpty()) "No matches in the catalog — try the network search below"
                else "You already have everything that matches",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp)
            )
        }
    }

    val shown = if (expanded) missing else missing.take(CATALOG_COLLAPSED)
    items(shown, key = { "cat-${it.key}" }) { t ->
        CatalogTrackRow(
            track = t,
            getState = state.getStates[t.key] ?: GetButtonState(),
            onGet = { onGet(t) },
            onPlay = onPlay,
            onChooseSource = { onChooseSource(t) }
        )
    }
    if (missing.size > CATALOG_COLLAPSED) {
        item("catalog-more") {
            TextButton(onClick = onToggleExpanded, modifier = Modifier.padding(horizontal = 8.dp)) {
                Text(if (expanded) "Show fewer" else "Show ${missing.size - CATALOG_COLLAPSED} more")
            }
        }
    }

    // AI: for descriptions a catalog can't match ("the song from the Drive soundtrack").
    val ai = state.aiTracks
    when {
        state.isAiSearching -> item("ai-busy") {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
            ) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(8.dp))
                Text("Asking AI which songs you mean…", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        ai != null -> {
            item("ai-h") { SubHeader("AI suggestions") }
            if (ai.isEmpty()) {
                item("ai-empty") {
                    Text("The AI couldn't place that one — try the artist, a lyric, or where you heard it",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                }
            }
            items(ai.filter { it.key !in state.pinned }, key = { "ai-${it.key}" }) { t ->
                CatalogTrackRow(
                    track = t,
                    getState = state.getStates[t.key] ?: GetButtonState(),
                    onGet = { onGet(t) },
                    onPlay = onPlay,
                    onChooseSource = { onChooseSource(t) }
                )
            }
        }
        state.aiAvailable && state.hasCatalogSearched -> item("ai-ask") {
            TextButton(onClick = onAskAi, modifier = Modifier.padding(horizontal = 8.dp)) {
                Icon(Icons.Default.AutoAwesome, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(6.dp))
                Text("Not it? Ask AI which song you mean")
            }
        }
    }
}

// endregion

// region Get more section

private fun androidx.compose.foundation.lazy.LazyListScope.getMoreSection(
    state: SearchUiState,
    onSearchOnline: () -> Unit,
    onTrigger: (DownloadResult) -> Unit,
    onPlay: (String) -> Unit
) {
    if (state.query.isBlank()) return

    item("getmore-h") {
        Spacer(modifier = Modifier.height(16.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 4.dp)
        ) {
            Text(
                text = "Network sources",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.weight(1f)
            )
            if (state.isDownloadSearching) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(
                        strokeWidth = 2.dp,
                        modifier = Modifier.size(16.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        "Searching network",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else if (state.hasDownloadSearched) {
                TextButton(onClick = onSearchOnline) {
                    Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Search again")
                }
            } else {
                FilledTonalButton(onClick = onSearchOnline) {
                    Icon(Icons.Default.CloudDownload, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Search network")
                }
            }
        }
        if (state.parsedArtist.isNotBlank() && state.hasDownloadSearched) {
            Text(
                text = "Parsed: artist=\"${state.parsedArtist}\" track=\"${state.parsedTrack}\"",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp)
            )
        }
    }

    if (state.downloadError != null) {
        item("dl-err") { ErrorBanner(text = state.downloadError) }
    }

    state.libraryMatchId?.let { trackId ->
        item("dl-have") {
            InfoBanner(
                icon = Icons.Default.LibraryMusic,
                text = "You already have this song",
                actionLabel = "Play",
                onAction = { onPlay(trackId) }
            )
        }
    }

    if (state.hasDownloadSearched && state.downloadResults.isEmpty() && !state.isDownloadSearching) {
        item("dl-empty") {
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerLow,
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp)
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(12.dp)
                ) {
                    Icon(
                        Icons.Default.SearchOff,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.width(12.dp))
                    Text(
                        text = "No matches found on the network.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }

    // Rows already under "Your downloads" aren't repeated here.
    val fresh = state.downloadResults.filter { it.key() !in state.pinned }
    if (fresh.isNotEmpty()) {
        items(fresh, key = { it.key() }) { result ->
            DownloadCandidateRow(
                result = result,
                getState = state.getStates[result.key()] ?: GetButtonState(),
                onTrigger = { onTrigger(result) },
                onPlay = onPlay
            )
        }
    }
}

// endregion

// region Your downloads

private fun androidx.compose.foundation.lazy.LazyListScope.yourDownloadsSection(
    state: SearchUiState,
    onPlay: (String) -> Unit,
    onRetry: (String) -> Unit,
    onClearFinished: () -> Unit
) {
    if (state.pinned.isEmpty()) return
    item("yours-h") {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, end = 8.dp, top = 8.dp)
        ) {
            Text(
                text = "Your downloads",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.weight(1f)
            )
            if (state.pinned.keys.any { state.getStates[it]?.inFlight != true }) {
                TextButton(onClick = onClearFinished) { Text("Clear finished") }
            }
        }
    }
    items(state.pinned.entries.toList().asReversed(), key = { "yours-${it.key}" }) { (key, row) ->
        val gs = state.getStates[key] ?: GetButtonState()
        when {
            row.catalog != null -> CatalogTrackRow(
                track = row.catalog.copy(inLibrary = false),
                getState = gs,
                onGet = { onRetry(key) },
                onPlay = onPlay,
                onChooseSource = null
            )
            row.file != null -> DownloadCandidateRow(
                result = row.file,
                getState = gs,
                onTrigger = { onRetry(key) },
                onPlay = onPlay
            )
        }
    }
}

@Composable
private fun StatusBanners(state: SearchUiState) {
    Column {
        if (!state.soulseekOnline) {
            InfoBanner(
                icon = Icons.Default.CloudOff,
                text = "Soulseek is offline on the server — downloads will wait until it reconnects"
            )
        }
        state.statusError?.let { ErrorBanner(text = it) }
    }
}

@Composable
private fun InfoBanner(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    text: String,
    actionLabel: String? = null,
    onAction: () -> Unit = {}
) {
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 8.dp)
        ) {
            Icon(icon, contentDescription = null)
            Spacer(modifier = Modifier.width(12.dp))
            Text(text = text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            if (actionLabel != null) {
                TextButton(onClick = onAction) { Text(actionLabel) }
            }
        }
    }
}

// endregion

// region Active / Recent

@Composable
private fun ActiveDownloadsSection(
    transfers: List<TransferInfo>,
    activeJobs: List<JobInfo>,
    progress: Map<String, JobProgress>,
    onCancel: (TransferInfo) -> Unit
) {
    if (transfers.isEmpty() && activeJobs.isEmpty()) return
    Column(modifier = Modifier.padding(top = 8.dp)) {
        SectionHeader("Active downloads")
        ActiveTransfersList(transfers = transfers, progress = progress, onCancel = onCancel)
        if (activeJobs.isNotEmpty()) {
            SubHeader("Queued (${activeJobs.size})")
            activeJobs.forEach { job ->
                ListItem(
                    headlineContent = {
                        Text(job.description?.takeIf { it.isNotBlank() } ?: job.type)
                    },
                    supportingContent = {
                        Text(
                            text = job.status.replaceFirstChar { it.uppercase() },
                            style = MaterialTheme.typography.bodySmall
                        )
                    },
                    leadingContent = { Icon(Icons.Default.Work, contentDescription = null) }
                )
            }
        }
    }
}

@Composable
private fun ActiveTransfersList(
    transfers: List<TransferInfo>,
    progress: Map<String, JobProgress>,
    onCancel: (TransferInfo) -> Unit
) {
    Column {
        transfers.forEach { transfer ->
            TransferItem(transfer = transfer, onCancel = { onCancel(transfer) })
        }
    }
}

@Composable
private fun TransferItem(transfer: TransferInfo, onCancel: () -> Unit) {
    Column {
        ListItem(
            headlineContent = {
                Text(
                    text = transfer.displayName,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            },
            supportingContent = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    TransferStateBadge(state = transfer.state)
                    if (transfer.state.equals("Transferring", ignoreCase = true)) {
                        Text(
                            text = buildString {
                                if (transfer.speedMbps.isNotEmpty()) append(transfer.speedMbps)
                                append(" · ${transfer.progress.toInt()}%")
                                transfer.etaSeconds?.let { append(" · ETA ${it}s") }
                            },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    transfer.error?.let { err ->
                        Text(
                            text = err,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error
                        )
                    }
                }
            },
            trailingContent = {
                val isActive = transfer.state.lowercase() in
                        setOf("requested", "queued", "connected", "transferring")
                if (isActive) {
                    IconButton(onClick = onCancel) {
                        Icon(
                            Icons.Default.Cancel,
                            contentDescription = "Cancel",
                            tint = MaterialTheme.colorScheme.error
                        )
                    }
                }
            }
        )

        AnimatedVisibility(visible = transfer.state.equals("Transferring", ignoreCase = true)) {
            LinearProgressIndicator(
                progress = { transfer.progress / 100f },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
                    .padding(bottom = 8.dp)
            )
        }
    }
}

@Composable
private fun TransferStateBadge(state: String) {
    val (containerColor, contentColor) = when (state.lowercase()) {
        "queued" -> MaterialTheme.colorScheme.secondaryContainer to MaterialTheme.colorScheme.onSecondaryContainer
        "transferring" -> MaterialTheme.colorScheme.primaryContainer to MaterialTheme.colorScheme.onPrimaryContainer
        "completed" -> Color(0xFF2E7D32) to Color.White
        "failed", "denied" -> MaterialTheme.colorScheme.errorContainer to MaterialTheme.colorScheme.onErrorContainer
        else -> MaterialTheme.colorScheme.surfaceVariant to MaterialTheme.colorScheme.onSurfaceVariant
    }
    SuggestionChip(
        onClick = {},
        label = { Text(state, style = MaterialTheme.typography.labelSmall) },
        colors = SuggestionChipDefaults.suggestionChipColors(
            containerColor = containerColor,
            labelColor = contentColor
        ),
        modifier = Modifier.height(24.dp)
    )
}

@Composable
private fun RecentDownloadsSection(
    expanded: Boolean,
    onToggle: () -> Unit,
    recents: List<JobInfo>,
    onRefresh: () -> Unit,
    onPlay: (String) -> Unit
) {
    Column(modifier = Modifier.padding(top = 8.dp)) {
        Surface(
            onClick = onToggle,
            color = Color.Transparent,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 8.dp)
            ) {
                Icon(
                    if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Recent downloads",
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f)
                )
                if (expanded) {
                    IconButton(onClick = onRefresh, modifier = Modifier.size(32.dp)) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh", modifier = Modifier.size(18.dp))
                    }
                }
            }
        }
        AnimatedVisibility(visible = expanded) {
            Column {
                if (recents.isEmpty()) {
                    Text(
                        text = "No recent downloads",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                    )
                } else {
                    recents.take(20).forEach { job ->
                        val statusColor = when (job.status.lowercase()) {
                            "completed", "complete" -> Color(0xFF2E7D32)
                            "failed", "error" -> MaterialTheme.colorScheme.error
                            "running", "in_progress" -> Color(0xFFED6C02)
                            else -> MaterialTheme.colorScheme.onSurfaceVariant
                        }
                        val headline = job.description?.takeIf { it.isNotBlank() }
                            ?: job.type.replace("_", " ").replaceFirstChar { it.uppercase() }
                        ListItem(
                            headlineContent = {
                                Text(headline, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            },
                            supportingContent = {
                                val statusText = when {
                                    job.alreadyInLibrary -> "Already in your library"
                                    job.status.equals("failed", true) && !job.error.isNullOrBlank() -> job.error
                                    else -> job.status.replaceFirstChar { it.uppercase() }
                                }
                                Text(
                                    text = statusText,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = statusColor,
                                    maxLines = 2,
                                    overflow = TextOverflow.Ellipsis
                                )
                            },
                            trailingContent = job.trackId?.let { id ->
                                {
                                    IconButton(onClick = { onPlay(id) }) {
                                        Icon(Icons.Default.PlayArrow, contentDescription = "Play")
                                    }
                                }
                            },
                            leadingContent = {
                                Icon(
                                    imageVector = when (job.status.lowercase()) {
                                        "completed", "complete" -> Icons.Default.Check
                                        "failed", "error" -> Icons.Default.ErrorOutline
                                        "running", "in_progress" -> Icons.Default.Sync
                                        else -> Icons.Default.Schedule
                                    },
                                    contentDescription = null,
                                    tint = statusColor
                                )
                            }
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun EmptyHint() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 48.dp, start = 32.dp, end = 32.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(
                Icons.Default.Search,
                contentDescription = null,
                modifier = Modifier.size(64.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "Search your library or the network",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Tip: type \"Artist - Track\" for sharper results",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

// endregion

// region Search bar / chips / common rows

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun M3SearchBar(query: String, onQueryChange: (String) -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerHigh,
        shape = RoundedCornerShape(28.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .height(56.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxSize()
                .padding(start = 16.dp, end = 8.dp)
        ) {
            Icon(
                Icons.Default.Search,
                contentDescription = "Search",
                tint = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.width(12.dp))
            BasicTextField(
                value = query,
                onValueChange = onQueryChange,
                singleLine = true,
                cursorBrush = androidx.compose.ui.graphics.SolidColor(MaterialTheme.colorScheme.primary),
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                modifier = Modifier
                    .weight(1f)
                    .padding(vertical = 8.dp),
                decorationBox = { inner ->
                    if (query.isEmpty()) {
                        Text(
                            text = "Search music",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                    inner()
                }
            )
            if (query.isNotEmpty()) {
                IconButton(
                    onClick = { onQueryChange("") },
                    modifier = Modifier.size(40.dp)
                ) {
                    Icon(
                        Icons.Default.Close,
                        contentDescription = "Clear",
                        tint = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun FilterChipRow(selected: SearchFilter, onSelect: (SearchFilter) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        SearchFilter.entries.forEach { f ->
            val isSelected = f == selected
            val label = when (f) {
                SearchFilter.ALL -> "All"
                SearchFilter.ALBUMS -> "Albums"
                SearchFilter.ARTISTS -> "Artists"
                SearchFilter.TRACKS -> "Tracks"
            }
            Surface(
                onClick = { onSelect(f) },
                shape = RoundedCornerShape(8.dp),
                color = if (isSelected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent,
                contentColor = if (isSelected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurface,
                border = if (isSelected) null else androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline)
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    if (isSelected) {
                        Icon(
                            Icons.Default.Check,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp)
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                    }
                    Text(label, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

private fun highlight(text: String, query: String, color: Color): AnnotatedString {
    if (query.isBlank()) return AnnotatedString(text)
    val idx = text.indexOf(query, ignoreCase = true)
    if (idx < 0) return AnnotatedString(text)
    return buildAnnotatedString {
        append(text.substring(0, idx))
        withStyle(SpanStyle(color = color, fontWeight = FontWeight.Bold)) {
            append(text.substring(idx, idx + query.length))
        }
        append(text.substring(idx + query.length))
    }
}

@Composable
private fun TopResultHero(query: String, album: Album, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceContainer,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(12.dp)
        ) {
            CoverArt(
                coverArtId = album.coverArt,
                contentDescription = album.name,
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(12.dp))
            )
            Spacer(modifier = Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "TOP RESULT",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = highlight(album.name, query, MaterialTheme.colorScheme.primary),
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "Album · ${album.artist}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.width(8.dp))
            Surface(
                onClick = onClick,
                shape = RoundedCornerShape(20.dp),
                color = MaterialTheme.colorScheme.primary,
                contentColor = MaterialTheme.colorScheme.onPrimary
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp)
                ) {
                    Icon(
                        Icons.Default.PlayArrow,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Play", style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}

@Composable
private fun ResultRow(
    kind: String,
    headline: String,
    sub: String,
    coverArtId: String?,
    query: String,
    onClick: () -> Unit
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 8.dp)
    ) {
        CoverArt(
            coverArtId = coverArtId,
            contentDescription = headline,
            modifier = Modifier
                .size(48.dp)
                .clip(RoundedCornerShape(8.dp))
        )
        Spacer(modifier = Modifier.width(14.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = kind.uppercase(),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = highlight(headline, query, MaterialTheme.colorScheme.primary),
                style = MaterialTheme.typography.titleSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Text(
                text = sub,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Icon(
            Icons.Default.ChevronRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 16.dp, top = 16.dp, bottom = 8.dp)
    )
}

@Composable
private fun SubHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 4.dp)
    )
}

@Composable
private fun ErrorBanner(text: String) {
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(12.dp)
        ) {
            Icon(
                Icons.Default.ErrorOutline,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onErrorContainer
            )
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = text,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer
            )
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TrackRow(
    track: Track,
    query: String,
    onClick: () -> Unit,
    onPlayNext: () -> Unit,
    onAddToQueue: () -> Unit,
    onToggleMarkForDeletion: () -> Unit,
    onStartRadio: () -> Unit
) {
    var showMenu by remember { mutableStateOf(false) }
    Box {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(onClick = onClick, onLongClick = { showMenu = true })
                .padding(horizontal = 16.dp, vertical = 8.dp)
        ) {
            CoverArt(
                coverArtId = track.coverArt,
                contentDescription = track.title,
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(8.dp))
            )
            Spacer(modifier = Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "TRACK",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = highlight(track.title, query, MaterialTheme.colorScheme.primary),
                    style = MaterialTheme.typography.titleSmall,
                    color = if (track.markedForDeletion) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "${track.artist} · ${formatDuration(track.duration)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            IconButton(onClick = { showMenu = true }, modifier = Modifier.size(36.dp)) {
                Icon(
                    Icons.Default.MoreVert,
                    contentDescription = "More",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(18.dp)
                )
            }
        }

        DropdownMenu(expanded = showMenu, onDismissRequest = { showMenu = false }) {
            DropdownMenuItem(
                text = { Text("Play") },
                onClick = { showMenu = false; onClick() },
                leadingIcon = { Icon(Icons.Default.PlayArrow, contentDescription = null) }
            )
            DropdownMenuItem(
                text = { Text("Play Next") },
                onClick = { showMenu = false; onPlayNext() },
                leadingIcon = { Icon(Icons.Default.QueuePlayNext, contentDescription = null) }
            )
            DropdownMenuItem(
                text = { Text("Add to Queue") },
                onClick = { showMenu = false; onAddToQueue() },
                leadingIcon = { Icon(Icons.Default.AddToQueue, contentDescription = null) }
            )
            DropdownMenuItem(
                text = { Text("Start Radio") },
                onClick = { showMenu = false; onStartRadio() },
                leadingIcon = { Icon(Icons.Default.Sensors, contentDescription = null) }
            )
            DropdownMenuItem(
                text = {
                    Text(
                        if (track.markedForDeletion) "Unmark for Deletion" else "Mark for Deletion",
                        color = if (!track.markedForDeletion) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface
                    )
                },
                onClick = { showMenu = false; onToggleMarkForDeletion() },
                leadingIcon = {
                    Icon(
                        if (track.markedForDeletion) Icons.Default.RestoreFromTrash else Icons.Default.DeleteOutline,
                        contentDescription = null,
                        tint = if (!track.markedForDeletion) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface
                    )
                }
            )
        }
    }
}

// endregion

// region Download candidate row

@Composable
internal fun DownloadCandidateRow(
    result: DownloadResult,
    getState: GetButtonState,
    onTrigger: () -> Unit,
    onPlay: (String) -> Unit
) {
    Surface(
        color = Color.Transparent,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp)
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = result.displayName,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                        modifier = Modifier.padding(top = 2.dp)
                    ) {
                        QualityChip(format = result.format, bitRate = result.bitRate)
                        Text(
                            text = result.sizeMb,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Text(
                            text = "·",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Text(
                            text = result.username,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false)
                        )
                        if (result.slotsFree == true || (result.freeUploadSlots ?: 0) > 0) {
                            Text(
                                text = "· free slot",
                                style = MaterialTheme.typography.labelSmall,
                                color = Color(0xFF2E7D32)
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.width(8.dp))
                GetButton(
                    getState = getState,
                    onClick = onTrigger,
                    onPlay = { getState.trackId?.let(onPlay) }
                )
            }
            DownloadStatusLine(getState)
        }
    }
}

/** Progress bar, stage, or failure reason under a download row. */
@Composable
private fun DownloadStatusLine(getState: GetButtonState) {
    if (getState.state == GetState.Downloading && getState.total > 0) {
        LinearProgressIndicator(
            progress = { getState.pct / 100f },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 4.dp)
        )
        Text(
            text = listOfNotNull(
                "${getState.pct.toInt()}% · ${formatBytes(getState.received)} / ${formatBytes(getState.total)}",
                getState.detail
            ).joinToString(" · "),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    } else if (getState.state == GetState.Failed && getState.error != null) {
        Text(
            text = getState.error,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.error
        )
    } else if (getState.detail != null && getState.state != GetState.Idle) {
        Text(
            text = getState.detail,
            style = MaterialTheme.typography.labelSmall,
            color = if (getState.state == GetState.Done) Color(0xFF2E7D32)
            else MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/** A catalog song: owned (Play) or not (Get, or pick the file yourself). */
@Composable
internal fun CatalogTrackRow(
    track: CatalogTrack,
    getState: GetButtonState,
    onGet: () -> Unit,
    onPlay: (String) -> Unit,
    onChooseSource: (() -> Unit)?
) {
    var menuOpen by remember { mutableStateOf(false) }
    Column(
        verticalArrangement = Arrangement.spacedBy(4.dp),
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            coil.compose.AsyncImage(
                model = track.coverUrl,
                contentDescription = null,
                modifier = Modifier
                    .size(48.dp)
                    .clip(RoundedCornerShape(6.dp))
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = track.title,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = listOfNotNull(
                        track.artist,
                        track.album?.takeIf { it.isNotBlank() },
                        track.duration?.takeIf { it > 0 }?.let { formatDuration(it) }
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Spacer(modifier = Modifier.width(8.dp))
            if (track.inLibrary && track.trackId != null && getState.state == GetState.Idle) {
                FilledTonalButton(onClick = { onPlay(track.trackId) }) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Play", style = MaterialTheme.typography.labelLarge)
                }
            } else {
                GetButton(getState = getState, onClick = onGet, onPlay = { getState.trackId?.let(onPlay) })
            }
            if (onChooseSource != null && !track.inLibrary &&
                (getState.state == GetState.Idle || getState.state == GetState.Failed)) {
                Box {
                    IconButton(onClick = { menuOpen = true }, modifier = Modifier.size(36.dp)) {
                        Icon(Icons.Default.MoreVert, contentDescription = "More")
                    }
                    DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                        DropdownMenuItem(
                            text = { Text("Choose source…") },
                            leadingIcon = { Icon(Icons.Default.List, contentDescription = null) },
                            onClick = { menuOpen = false; onChooseSource() }
                        )
                    }
                }
            }
        }
        // Aligned under the title, past the 48dp cover + 12dp gap.
        Column(modifier = Modifier.padding(start = 60.dp)) {
            track.reason?.takeIf { it.isNotBlank() }?.let { why ->
                Text(
                    text = why,
                    style = MaterialTheme.typography.labelSmall,
                    fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            if (track.inLibrary && getState.state == GetState.Idle) {
                Text(
                    text = "In your library",
                    style = MaterialTheme.typography.labelSmall,
                    color = Color(0xFF2E7D32)
                )
            }
            DownloadStatusLine(getState)
        }
    }
}

@Composable
private fun QualityChip(format: String, bitRate: Int?) {
    val isFlac = format.equals("FLAC", ignoreCase = true)
    val br = bitRate ?: 0
    val (container, content) = when {
        isFlac -> MaterialTheme.colorScheme.tertiaryContainer to MaterialTheme.colorScheme.onTertiaryContainer
        br >= 320 -> MaterialTheme.colorScheme.primaryContainer to MaterialTheme.colorScheme.onPrimaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant to MaterialTheme.colorScheme.onSurfaceVariant
    }
    val label = if (isFlac) "FLAC" else if (br > 0) "$format ${br}k" else format
    Surface(
        color = container,
        contentColor = content,
        shape = RoundedCornerShape(4.dp)
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
        )
    }
}

@Composable
private fun GetButton(getState: GetButtonState, onClick: () -> Unit, onPlay: () -> Unit) {
    when (getState.state) {
        GetState.Idle -> {
            FilledTonalButton(onClick = onClick) {
                Icon(Icons.Default.Download, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("Get", style = MaterialTheme.typography.labelLarge)
            }
        }
        GetState.Searching -> {
            FilledTonalButton(onClick = {}, enabled = false) {
                CircularProgressIndicator(
                    strokeWidth = 2.dp,
                    modifier = Modifier.size(14.dp)
                )
                Spacer(modifier = Modifier.width(6.dp))
                Text(getState.label, style = MaterialTheme.typography.labelLarge)
            }
        }
        GetState.Downloading -> {
            FilledTonalButton(onClick = {}, enabled = false) {
                Text(
                    text = "${getState.pct.toInt()}%",
                    style = MaterialTheme.typography.labelLarge
                )
            }
        }
        GetState.Done -> {
            val canPlay = getState.trackId != null
            FilledTonalButton(
                onClick = onPlay,
                enabled = canPlay,
                colors = ButtonDefaults.filledTonalButtonColors(
                    containerColor = Color(0xFF2E7D32).copy(alpha = 0.18f),
                    contentColor = Color(0xFF2E7D32),
                    disabledContainerColor = Color(0xFF2E7D32).copy(alpha = 0.18f),
                    disabledContentColor = Color(0xFF2E7D32)
                )
            ) {
                Icon(
                    if (canPlay) Icons.Default.PlayArrow else Icons.Default.Check,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp)
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(if (canPlay) "Play" else "Done", style = MaterialTheme.typography.labelLarge)
            }
        }
        GetState.Failed -> {
            FilledTonalButton(
                onClick = onClick,
                colors = ButtonDefaults.filledTonalButtonColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                    contentColor = MaterialTheme.colorScheme.onErrorContainer
                )
            ) {
                Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(modifier = Modifier.width(4.dp))
                Text("Try another", style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

// endregion
