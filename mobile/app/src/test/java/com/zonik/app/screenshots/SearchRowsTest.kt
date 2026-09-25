package com.zonik.app.screenshots

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import coil.Coil
import com.android.ide.common.rendering.api.SessionParams
import com.zonik.app.data.api.CatalogTrack
import com.zonik.app.data.api.DownloadResult
import com.zonik.app.ui.screens.search.CatalogTrackRow
import com.zonik.app.ui.screens.search.DownloadCandidateRow
import com.zonik.app.ui.screens.search.GetButtonState
import com.zonik.app.ui.screens.search.GetState
import com.zonik.app.ui.theme.WithNeutralScheme
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** Every state a Search download row can be in, on one screen. */
class SearchRowsTest {
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

    private fun cat(title: String, artist: String, album: String, owned: Boolean = false) =
        CatalogTrack(title = title, artist = artist, album = album, duration = 245,
            coverUrl = "https://example.invalid/c.jpg", inLibrary = owned, trackId = if (owned) "t" else null)

    @Test
    fun rows() = paparazzi.snapshot {
        androidx.compose.runtime.CompositionLocalProvider(androidx.compose.ui.platform.LocalInspectionMode provides true) {
            WithNeutralScheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.surface) {
                    Column {
                        CatalogTrackRow(cat("Around the World", "Daft Punk", "Homework", owned = true), GetButtonState(), {}, {}, null)
                        CatalogTrackRow(cat("Digital Love", "Daft Punk", "Discovery"), GetButtonState(), {}, {}, {})
                        CatalogTrackRow(cat("Veridis Quo", "Daft Punk", "Discovery"),
                            GetButtonState(GetState.Searching, jobId = "j", label = "Finding", detail = "Finding a source"), {}, {}, {})
                        CatalogTrackRow(cat("Voyager", "Daft Punk", "Discovery"),
                            GetButtonState(GetState.Searching, jobId = "j", label = "Waiting", detail = "Waiting for the peer to start sending"), {}, {}, {})
                        CatalogTrackRow(cat("Face to Face", "Daft Punk", "Discovery"),
                            GetButtonState(GetState.Downloading, jobId = "j", pct = 43f, received = 13_000_000, total = 30_000_000,
                                detail = "2.1 MB/s · 8s left"), {}, {}, {})
                        CatalogTrackRow(cat("Something About Us", "Daft Punk", "Discovery"),
                            GetButtonState(GetState.Done, jobId = "j", trackId = "t", detail = "Added to your library"), {}, {}, {})
                        CatalogTrackRow(cat("Too Long", "Daft Punk", "Discovery"),
                            GetButtonState(GetState.Failed, jobId = "j", error = "All 5 sources failed: Peer did not respond in time"), {}, {}, {})
                        DownloadCandidateRow(
                            DownloadResult(username = "vinylhead", filename = "Music\\Daft Punk\\Discovery\\03 Digital Love.flac",
                                size = 32_000_000, extension = "flac", slotsFree = true),
                            GetButtonState(), {}, {}
                        )
                    }
                }
            }
        }
    }
}
