package com.zonik.app.ui.screens.login

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.zonik.app.ui.theme.ZonikShapes
import com.zonik.app.ui.util.qrBitmap
import com.zonik.core.auth.DiscoveredServer
import kotlinx.coroutines.delay

@Composable
fun LoginScreen(
    onLoginSuccess: () -> Unit,
    viewModel: LoginViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(uiState.isSuccess) {
        if (uiState.isSuccess) onLoginSuccess()
    }

    if (viewModel.isTv) {
        TvLoginScreen(viewModel, uiState)
    } else {
        PhoneLoginScreen(viewModel, uiState)
    }
}

// region Phone

@Composable
private fun PhoneLoginScreen(viewModel: LoginViewModel, uiState: LoginUiState) {
    BackHandler(enabled = uiState.step != LoginStep.PickServer) {
        viewModel.backToServers()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Spacer(Modifier.height(24.dp))
        Text(
            text = "Zonik",
            style = MaterialTheme.typography.displayLarge,
            color = MaterialTheme.colorScheme.primary
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Self-hosted music player",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(40.dp))

        when (uiState.step) {
            LoginStep.PickServer -> PhoneServerPicker(viewModel, uiState)
            LoginStep.Credentials -> PhoneCredentials(viewModel, uiState)
            LoginStep.Pairing -> PhonePairing(viewModel, uiState)
        }
    }
}

@Composable
private fun PhoneServerPicker(viewModel: LoginViewModel, uiState: LoginUiState) {
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            "Found on your network",
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(1f)
        )
        if (uiState.discovering) {
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
        } else {
            TextButton(onClick = viewModel::startDiscovery) { Text("Search again") }
        }
    }
    Spacer(Modifier.height(8.dp))

    if (uiState.servers.isEmpty()) {
        Text(
            text = if (uiState.discovering) "Looking for Zonik servers…"
            else "No server found. Enter its address below.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp)
        )
    }
    uiState.servers.forEach { server ->
        ServerCard(server = server, onClick = { viewModel.selectServer(server) })
        Spacer(Modifier.height(8.dp))
    }

    Spacer(Modifier.height(24.dp))
    Text(
        "Other server…",
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth()
    )
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = uiState.manualUrl,
        onValueChange = viewModel::updateManualUrl,
        label = { Text("Server address") },
        placeholder = { Text("zonik, zonik.lan or 10.0.0.205") },
        singleLine = true,
        isError = uiState.manualError != null,
        supportingText = uiState.manualError?.let { { Text(it) } },
        modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(
            keyboardType = KeyboardType.Uri,
            autoCorrectEnabled = false,
            imeAction = ImeAction.Go
        ),
        keyboardActions = KeyboardActions(onGo = {
            keyboard?.hide()
            focusManager.clearFocus()
            viewModel.submitManualUrl()
        })
    )
    Spacer(Modifier.height(12.dp))
    Button(
        onClick = viewModel::submitManualUrl,
        enabled = uiState.manualUrl.isNotBlank() && !uiState.checkingManual,
        modifier = Modifier.fillMaxWidth()
    ) {
        if (uiState.checkingManual) {
            CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
                color = MaterialTheme.colorScheme.onPrimary
            )
        } else {
            Text("Continue")
        }
    }
}

@Composable
private fun ServerCard(server: DiscoveredServer, onClick: () -> Unit) {
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        shape = ZonikShapes.cardShape,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)
    ) {
        ListItem(
            colors = ListItemDefaults.colors(containerColor = Color.Transparent),
            leadingContent = {
                Icon(Icons.Default.Dns, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            },
            headlineContent = { Text("${server.title} (${server.host})") },
            supportingContent = {
                Text(
                    listOfNotNull(server.url, server.version?.let { "v$it" }).joinToString(" · "),
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            },
            trailingContent = { Icon(Icons.Default.ChevronRight, contentDescription = null) }
        )
    }
}

@Composable
private fun SelectedServerRow(server: DiscoveredServer, onChange: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(Icons.Default.Dns, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(server.title, style = MaterialTheme.typography.titleMedium)
            Text(
                server.url,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        TextButton(onClick = onChange) { Text("Change") }
    }
}

@Composable
private fun PhoneCredentials(viewModel: LoginViewModel, uiState: LoginUiState) {
    val server = uiState.selected ?: return
    CredentialsForm(viewModel, uiState, server)
}

/**
 * Username + password (device token) or username + API key (legacy). Shared by the phone and
 * the TV's manual fallback. Every field advances with the IME's Next/Done action: on TV the
 * leanback IME is fullscreen and swallows D-pad DOWN, so there is no other way out of a field.
 */
@Composable
internal fun CredentialsForm(
    viewModel: LoginViewModel,
    uiState: LoginUiState,
    server: DiscoveredServer,
    modifier: Modifier = Modifier,
) {
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    var secretVisible by remember { mutableStateOf(false) }

    Column(modifier = modifier.fillMaxWidth()) {
        SelectedServerRow(server, onChange = viewModel::backToServers)
        Spacer(Modifier.height(20.dp))

        if (uiState.legacyServer) {
            Text(
                "This server is older and signs in with an API key (web UI → Settings).",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(12.dp))
        }

        OutlinedTextField(
            value = uiState.username,
            onValueChange = viewModel::updateUsername,
            label = { Text("Username") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false, imeAction = ImeAction.Next),
            keyboardActions = KeyboardActions(onNext = { focusManager.moveFocus(FocusDirection.Down) })
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = if (uiState.useApiKey) uiState.apiKey else uiState.password,
            onValueChange = if (uiState.useApiKey) viewModel::updateApiKey else viewModel::updatePassword,
            label = { Text(if (uiState.useApiKey) "API key" else "Password") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Password,
                autoCorrectEnabled = false,
                imeAction = ImeAction.Done
            ),
            keyboardActions = KeyboardActions(onDone = {
                keyboard?.hide()
                focusManager.clearFocus()
                viewModel.signIn()
            }),
            visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                IconButton(onClick = { secretVisible = !secretVisible }) {
                    Icon(
                        imageVector = if (secretVisible) Icons.Filled.Visibility else Icons.Filled.VisibilityOff,
                        contentDescription = if (secretVisible) "Hide" else "Show"
                    )
                }
            }
        )

        uiState.error?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.height(20.dp))
        Button(
            onClick = viewModel::signIn,
            enabled = !uiState.isLoading,
            modifier = Modifier.fillMaxWidth()
        ) {
            if (uiState.isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.size(20.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            } else {
                Text("Sign in")
            }
        }
        Spacer(Modifier.height(8.dp))
        TextButton(
            onClick = { viewModel.setUseApiKey(!uiState.useApiKey) },
            modifier = Modifier.align(Alignment.CenterHorizontally)
        ) {
            Text(if (uiState.useApiKey) "Use your password instead" else "Use an API key instead")
        }
        TextButton(
            onClick = { viewModel.startPairing(server) },
            modifier = Modifier.align(Alignment.CenterHorizontally)
        ) {
            Text("Pair with a code instead")
        }
    }
}

@Composable
private fun PhonePairing(viewModel: LoginViewModel, uiState: LoginUiState) {
    val pairing = uiState.pairing ?: return
    SelectedServerRow(pairing.server, onChange = viewModel::backToServers)
    Spacer(Modifier.height(24.dp))
    PairingCodeBlock(pairing, codeSize = 56.sp, qrSize = 200.dp)
    Spacer(Modifier.height(24.dp))
    OutlinedButton(onClick = viewModel::renewCode, modifier = Modifier.fillMaxWidth()) { Text("New code") }
    Spacer(Modifier.height(8.dp))
    TextButton(
        onClick = { viewModel.stopPairing(); viewModel.selectServer(pairing.server) },
    ) { Text("Sign in with a password instead") }
}

// endregion

// region Shared pairing pieces

/** Seconds left until [expiresAtMs], ticking once a second. */
@Composable
internal fun rememberSecondsLeft(expiresAtMs: Long): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(expiresAtMs) {
        while (true) {
            now = System.currentTimeMillis()
            delay(1000)
        }
    }
    return ((expiresAtMs - now) / 1000).coerceAtLeast(0)
}

internal fun formatCountdown(seconds: Long): String = "%d:%02d".format(seconds / 60, seconds % 60)

/** The server's address for the "open … /pair" hint, without the scheme. */
internal fun pairHint(server: DiscoveredServer): String =
    server.url.substringAfter("://").trimEnd('/') + "/pair"

/** Code, QR (stacked) and status for the phone; the TV lays the same pieces out side by side. */
@Composable
private fun PairingCodeBlock(pairing: PairingUi, codeSize: androidx.compose.ui.unit.TextUnit, qrSize: Dp) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
        if (pairing.code == null) {
            CircularProgressIndicator()
            Spacer(Modifier.height(12.dp))
            Text(
                pairing.error ?: "Getting a pairing code…",
                color = if (pairing.error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium
            )
            return@Column
        }
        Text(
            pairing.code,
            style = MaterialTheme.typography.displayLarge.copy(
                fontSize = codeSize,
                letterSpacing = 8.sp,
                fontWeight = FontWeight.Bold
            ),
            color = MaterialTheme.colorScheme.primary
        )
        Spacer(Modifier.height(16.dp))
        pairing.approveUrl?.let { QrImage(it, qrSize) }
        Spacer(Modifier.height(16.dp))
        Text(
            "Scan with your phone or open ${pairHint(pairing.server)}",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(8.dp))
        val left = rememberSecondsLeft(pairing.expiresAtMs)
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(8.dp))
            Text(
                if (left > 0) "Waiting for approval · code expires in ${formatCountdown(left)}" else "Getting a new code…",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        pairing.error?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
    }
}

/** A locally rendered QR code on a white tile (scanners want a light quiet zone). */
@Composable
internal fun QrImage(content: String, size: Dp) {
    val bitmap = remember(content) { qrBitmap(content, 512) }
    if (bitmap == null) return
    Box(
        modifier = Modifier
            .size(size)
            .background(Color.White, RoundedCornerShape(12.dp))
            .padding(8.dp)
    ) {
        Image(
            bitmap = bitmap.asImageBitmap(),
            contentDescription = "QR code to approve this device",
            filterQuality = FilterQuality.None,
            modifier = Modifier.fillMaxSize()
        )
    }
}

// endregion
