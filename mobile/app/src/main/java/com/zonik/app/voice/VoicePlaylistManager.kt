package com.zonik.app.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import androidx.lifecycle.ViewModel
import com.zonik.app.data.api.CatalogTrack
import com.zonik.app.data.api.DownloadTriggerRequest
import com.zonik.app.data.api.VoicePlaylistRequest
import com.zonik.app.data.api.friendlyError
import com.zonik.app.data.api.ZonikApi
import com.zonik.app.data.repository.LibraryRepository
import com.zonik.app.media.PlaybackManager
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

/** UI state for the voice-playlist overlay. null = hidden. */
sealed interface VoiceState {
    /** Mic is open; [partial] is the live (possibly empty) transcript. */
    data class Listening(val partial: String) : VoiceState
    /** Transcript captured; the backend is building the mix. */
    data class Curating(val query: String) : VoiceState
    /** Mix assembled; about to play. */
    data class Picked(val name: String, val count: Int) : VoiceState
    /** Something went wrong; show [message] + a dismiss/retry. */
    data class Failed(val message: String) : VoiceState
    /**
     * Songs that fit the request but aren't in the library. [playing] tracks
     * from the library are already playing (0 when nothing there fit).
     */
    data class Missing(val name: String, val playing: Int, val missing: List<CatalogTrack>) : VoiceState
    /** Downloads started (or failed to start) for the missing songs. */
    data class Getting(val started: Int, val failed: Int) : VoiceState
}

/**
 * App-wide brain for the AI voice-playlist feature: captures a spoken request
 * (phone mic via [SpeechRecognizer]), sends the transcript to
 * `POST /api/assistant/voice-playlist`, resolves the returned track IDs to
 * playable tracks, and starts playback. Exposes a single [state] flow that the
 * root overlay renders. A @Singleton so the mic button and the overlay (which
 * live in different composition scopes) share one source of truth.
 */
@Singleton
class VoicePlaylistManager @Inject constructor(
    @ApplicationContext private val appContext: Context,
    private val api: ZonikApi,
    private val library: LibraryRepository,
    private val playback: PlaybackManager,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val _state = MutableStateFlow<VoiceState?>(null)
    val state: StateFlow<VoiceState?> = _state.asStateFlow()

    private var recognizer: SpeechRecognizer? = null
    private var size: Int = 50
    private var lastQuery: String? = null

    /**
     * Begin a listening session. Must be called on the main thread with
     * RECORD_AUDIO already granted. SpeechRecognizer auto-detects end of speech
     * and delivers the final transcript via onResults → [submitQuery].
     */
    fun startListening() {
        if (!SpeechRecognizer.isRecognitionAvailable(appContext)) {
            _state.value = VoiceState.Failed("Speech recognition isn't available on this device.")
            return
        }
        cancelRecognizer()
        val sr = SpeechRecognizer.createSpeechRecognizer(appContext)
        recognizer = sr
        sr.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) { _state.value = VoiceState.Listening("") }
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onPartialResults(partial: Bundle?) {
                val text = partial?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (!text.isNullOrBlank()) _state.value = VoiceState.Listening(text)
            }
            override fun onResults(results: Bundle?) {
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                cancelRecognizer()
                submitQuery(text)
            }
            override fun onError(error: Int) {
                cancelRecognizer()
                _state.value = VoiceState.Failed(errorMessage(error))
            }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            // FREE_FORM is critical — preserves arbitrary phrases like "make me a road trip playlist".
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        _state.value = VoiceState.Listening("")
        try {
            sr.startListening(intent)
        } catch (e: Exception) {
            _state.value = VoiceState.Failed("Couldn't start listening: ${e.message}")
        }
    }

    /** Stop capturing early (e.g. user released a hold). Final transcript still arrives via onResults. */
    fun stopListening() {
        try { recognizer?.stopListening() } catch (_: Exception) {}
    }

    /**
     * Curate + play from a transcript directly (skips STT). Used by onResults and
     * available for surfaces that already have a text query (Android Auto, tests).
     */
    fun submitQuery(query: String) {
        val q = query.trim()
        if (q.isBlank()) {
            _state.value = VoiceState.Failed("Didn't catch that — try again.")
            return
        }
        lastQuery = q
        _state.value = VoiceState.Curating(q)
        scope.launch {
            try {
                val resp = withContext(Dispatchers.IO) {
                    api.voicePlaylist(VoicePlaylistRequest(prompt = q, size = size))
                }
                if (resp.error != null || resp.trackIds.isEmpty()) {
                    if (resp.missing.isNotEmpty()) {
                        // Nothing in the library fits, but real songs do.
                        _state.value = VoiceState.Missing(resp.name.ifBlank { q }, 0, resp.missing)
                    } else {
                        _state.value = VoiceState.Failed(resp.error ?: "Couldn't build a mix for that — try rephrasing.")
                    }
                    return@launch
                }
                _state.value = VoiceState.Picked(resp.name.ifBlank { "Your mix" }, resp.trackCount)
                val tracks = withContext(Dispatchers.IO) { resolveTracks(resp.trackIds) }
                if (tracks.isEmpty()) {
                    _state.value = VoiceState.Failed("Found a mix, but couldn't load its tracks from the server.")
                    return@launch
                }
                playback.playTracks(tracks)
                // Now Playing auto-opens via PlaybackManager.playbackRequested. Dismiss the
                // overlay — unless there are songs to offer, which stays up over it.
                _state.value = if (resp.missing.isNotEmpty())
                    VoiceState.Missing(resp.name.ifBlank { "Your mix" }, tracks.size, resp.missing)
                else null
            } catch (e: Exception) {
                _state.value = VoiceState.Failed(friendlyError(e))
            }
        }
    }

    /**
     * Tracks for [ids] in order. The local DB lags the server until the next sync,
     * so ids it doesn't have yet are fetched from the server — they used to be
     * dropped, and a mix of new arrivals played nothing.
     */
    private suspend fun resolveTracks(ids: List<String>) =
        library.getTracksByIdsPadded(ids).mapIndexedNotNull { i, t ->
            t ?: try { library.fetchTrack(ids[i]) } catch (_: Exception) { null }
        }

    /** Ask again with the last query (after a failure). */
    fun retry() {
        lastQuery?.let { submitQuery(it) } ?: dismiss()
    }

    /** Start downloads for the songs offered in [VoiceState.Missing]. */
    fun getMissing() {
        val s = _state.value as? VoiceState.Missing ?: return
        scope.launch {
            var started = 0
            var failed = 0
            for (t in s.missing) {
                try {
                    val r = withContext(Dispatchers.IO) {
                        api.triggerDownload(DownloadTriggerRequest(artist = t.artist, track = t.title))
                    }
                    if (r.error == null) started++ else failed++
                } catch (_: Exception) {
                    failed++
                }
            }
            _state.value = VoiceState.Getting(started, failed)
            kotlinx.coroutines.delay(4_000)
            if (_state.value is VoiceState.Getting) _state.value = null
        }
    }

    /** Dismiss the overlay and tear down any active recognizer. */
    fun dismiss() {
        cancelRecognizer()
        _state.value = null
    }

    private fun cancelRecognizer() {
        recognizer?.let {
            try { it.cancel() } catch (_: Exception) {}
            try { it.destroy() } catch (_: Exception) {}
        }
        recognizer = null
    }

    private fun errorMessage(code: Int): String = when (code) {
        SpeechRecognizer.ERROR_NO_MATCH -> "Didn't catch that — try again."
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Didn't hear anything — try again."
        SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network error during recognition."
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "Microphone permission is required."
        SpeechRecognizer.ERROR_AUDIO -> "Microphone error — try again."
        else -> "Speech recognition failed (code $code)."
    }
}

/** Thin VM so composables in any scope reach the shared [VoicePlaylistManager]. */
@HiltViewModel
class VoiceViewModel @Inject constructor(
    private val manager: VoicePlaylistManager,
) : ViewModel() {
    val state: StateFlow<VoiceState?> = manager.state
    fun startListening() = manager.startListening()
    fun stopListening() = manager.stopListening()
    fun submitQuery(query: String) = manager.submitQuery(query)
    fun dismiss() = manager.dismiss()
    fun retry() = manager.retry()
    fun getMissing() = manager.getMissing()
}
