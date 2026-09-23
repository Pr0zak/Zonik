package com.zonik.app.screenshots

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import coil.Coil
import com.android.ide.common.rendering.api.SessionParams
import com.zonik.app.data.repository.SyncState
import com.zonik.app.ui.screens.home.HomeContent
import com.zonik.app.ui.screens.library.AlbumDetailContent
import com.zonik.app.ui.screens.library.TrackSort
import com.zonik.app.ui.screens.library.TracksTab
import com.zonik.app.ui.screens.playlists.PlaylistListScreen
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.zonik.app.ui.theme.WithNeutralScheme
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class ScreensTest {
    @get:Rule
    val paparazzi = Paparazzi(
        deviceConfig = DeviceConfig.PIXEL_6,
        theme = "android:Theme.Material.NoActionBar",
        renderingMode = SessionParams.RenderingMode.SHRINK,
        showSystemUi = false,
    )

    @Before
    fun images() {
        Coil.setImageLoader(fakeImageLoader(paparazzi.context))
    }

    @Test
    fun home() = paparazzi.snapshot {
        Screen {
            HomeContent(
                syncState = SyncState(),
                recentTracks = SampleData.tracks,
                recentlyPlayed = SampleData.tracks.take(6),
                onShuffleMix = {}, onNeglectedGems = {}, onShuffleRecentlyAdded = {},
                onShuffleNewestByYear = {}, onSyncNow = {},
                onNavigateToLibraryTracks = {}, onNavigateToLibraryFavorites = {},
                onPlayTrack = {}, onPlayNext = {}, onAddToQueue = {},
                onToggleMarkForDeletion = {}, onStartRadio = {},
            )
        }
    }

    @Test
    fun album() = paparazzi.snapshot {
        Screen {
            AlbumDetailContent(
                album = SampleData.album, tracks = SampleData.albumTracks,
                onPlayAll = {}, onShuffle = {}, onStar = {}, onTrackClick = {},
                onPlayNext = {}, onAddToQueue = {}, onGoToArtist = {},
                onToggleMarkForDeletion = {}, onStartRadio = {},
            )
        }
    }

    @Test
    fun playlists() = paparazzi.snapshot {
        Screen {
            PlaylistListScreen(playlists = SampleData.playlists, isLoading = false, error = null, onPlaylistClick = {})
        }
    }

    @Test
    fun libraryTracks() = paparazzi.snapshot {
        Screen {
            TracksTab(
                tracks = SampleData.tracks, tracksRecentFirst = SampleData.tracks,
                trackSort = TrackSort.entries.first(), trackSortAsc = true,
                onSetSort = {}, onPlayAll = {}, onShuffleAll = {}, onPlay = {},
                onPlayNext = {}, onAddToQueue = {}, onStartRadio = {}, onToggleMarkForDeletion = {},
            )
        }
    }
}

@Composable
private fun Screen(content: @Composable () -> Unit) {
    // Surface supplies the content colour the app's Scaffolds normally provide.
    // Inspection mode makes Coil draw each image's placeholder synchronously (the stand-in
    // cover from fakeImageLoader), where an async load would miss Paparazzi's single frame.
    androidx.compose.runtime.CompositionLocalProvider(androidx.compose.ui.platform.LocalInspectionMode provides true) {
        WithNeutralScheme {
            Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surface) { content() }
        }
    }
}
