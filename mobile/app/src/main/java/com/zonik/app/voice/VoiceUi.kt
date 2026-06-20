package com.zonik.app.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel

/**
 * Mic IconButton for the Home/Library top bar. Tap to start a voice request —
 * requests RECORD_AUDIO on first use, then opens the recognizer (auto-ends on
 * silence). Shares the [VoicePlaylistManager] singleton with [VoiceOverlay].
 */
@Composable
fun VoiceMicButton(
    modifier: Modifier = Modifier,
    viewModel: VoiceViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    var pendingStart by remember { mutableStateOf(false) }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted && pendingStart) viewModel.startListening()
        pendingStart = false
    }

    IconButton(
        modifier = modifier,
        onClick = {
            val granted = ContextCompat.checkSelfPermission(
                context, Manifest.permission.RECORD_AUDIO
            ) == PackageManager.PERMISSION_GRANTED
            if (granted) {
                viewModel.startListening()
            } else {
                pendingStart = true
                permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
    ) {
        Icon(Icons.Filled.Mic, contentDescription = "Voice playlist")
    }
}

/**
 * App-root overlay that renders the current voice-playlist [VoiceState] over any
 * screen: Listening → Curating → Picked, or a Failed card with a dismiss. Hidden
 * when state is null. Hosted once at the navigation root.
 */
@Composable
fun VoiceOverlay(
    viewModel: VoiceViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsState()
    val s = state ?: return

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.55f))
            .clickable(
                enabled = s is VoiceState.Failed || s is VoiceState.Listening,
                onClick = { viewModel.dismiss() }
            ),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            shape = RoundedCornerShape(24.dp),
            color = MaterialTheme.colorScheme.surface,
            tonalElevation = 6.dp,
            modifier = Modifier
                .fillMaxWidth(0.82f)
                .padding(24.dp),
        ) {
            Column(
                modifier = Modifier.padding(28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                when (s) {
                    is VoiceState.Listening -> {
                        Icon(
                            Icons.Filled.Mic,
                            contentDescription = null,
                            modifier = Modifier.size(40.dp),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Text("Listening…", style = MaterialTheme.typography.titleMedium)
                        if (s.partial.isNotBlank()) {
                            Text(
                                "“${s.partial}”",
                                style = MaterialTheme.typography.bodyMedium,
                                fontStyle = FontStyle.Italic,
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        } else {
                            Text(
                                "Say something like “play Christmas music” or “make me a road trip mix”.",
                                style = MaterialTheme.typography.bodySmall,
                                textAlign = TextAlign.Center,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    is VoiceState.Curating -> {
                        CircularProgressIndicator(modifier = Modifier.size(40.dp), strokeWidth = 3.dp)
                        Text("Building your mix…", style = MaterialTheme.typography.titleMedium)
                        Text(
                            "“${s.query}”",
                            style = MaterialTheme.typography.bodyMedium,
                            fontStyle = FontStyle.Italic,
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    is VoiceState.Picked -> {
                        Icon(
                            Icons.Filled.Check,
                            contentDescription = null,
                            modifier = Modifier.size(40.dp),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Text(s.name, style = MaterialTheme.typography.titleMedium, textAlign = TextAlign.Center)
                        Text(
                            "Picked ${s.count} tracks — starting playback",
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    is VoiceState.Failed -> {
                        Icon(
                            Icons.Filled.ErrorOutline,
                            contentDescription = null,
                            modifier = Modifier.size(40.dp),
                            tint = MaterialTheme.colorScheme.error,
                        )
                        Text(
                            s.message,
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center,
                        )
                        Button(onClick = { viewModel.dismiss() }) { Text("Dismiss") }
                    }
                }
            }
        }
    }
}
