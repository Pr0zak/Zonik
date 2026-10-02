package com.zonik.app.screenshots

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.android.ide.common.rendering.api.SessionParams
import com.android.resources.Density
import com.android.resources.ScreenOrientation
import com.zonik.app.ui.theme.WithNeutralScheme
import com.zonik.app.ui.tv.DemoEffect
import com.zonik.app.ui.tv.TvVisualizerSettingsContent
import com.zonik.app.ui.tv.VisualizerSettingsActions
import com.zonik.app.ui.tv.VisualizerSettingsState
import org.junit.Rule
import org.junit.Test

/** The TV visualizer page at a 1080p TV's 960x540dp, inside the same overscan margin the app uses. */
class TvVisualizerSettingsTest {
    @get:Rule
    val paparazzi = Paparazzi(
        deviceConfig = DeviceConfig(
            screenHeight = 1080, screenWidth = 1920, xdpi = 320, ydpi = 320,
            orientation = ScreenOrientation.LANDSCAPE, density = Density.XHIGH,
        ),
        theme = "android:Theme.Material.NoActionBar",
        renderingMode = SessionParams.RenderingMode.NORMAL,
        showSystemUi = false,
    )

    @Test
    fun visualizerSettings() = paparazzi.snapshot {
        WithNeutralScheme {
            Surface(Modifier.fillMaxSize(), color = Color(0xFF0E0D14)) {
                Box(Modifier.fillMaxSize().padding(horizontal = 48.dp, vertical = 27.dp)) {
                    // A few effects left out, to show the off style.
                    val off = setOf(DemoEffect.VORONOI, DemoEffect.CITY, DemoEffect.ASCII)
                    TvVisualizerSettingsContent(
                        state = VisualizerSettingsState(
                            ambientOn = true, delaySec = 60, beatOn = true, rotateSec = 60,
                            infoMode = "FADE", transition = -1, transitionMs = 1600, colors = "ALBUM", trails = false,
                            enabled = DemoEffect.entries.filter { it !in off }, isPlaying = true,
                        ),
                        actions = VisualizerSettingsActions({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}),
                    ) {
                        // GL does not render here; a gradient stands in for the live preview.
                        Box(
                            Modifier.fillMaxSize().background(
                                Brush.linearGradient(listOf(Color(0xFF3B1E6E), Color(0xFF0D3B52)))
                            )
                        )
                    }
                }
            }
        }
    }
}
