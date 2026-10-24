package com.zonik.app.ui.screens.login

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.zonik.app.ui.theme.ZonikShapes
import com.zonik.app.ui.util.tvFocusLift
import com.zonik.core.auth.DiscoveredServer
import kotlinx.coroutines.delay

/**
 * TV sign-in, D-pad only. Nothing to type by default: the TV finds the server on the LAN,
 * picks it when it is the only one, and shows a pairing code + QR that a signed-in phone or
 * browser approves. A manual address field (with the same shorthand as the phone) and a
 * username/password form are fallbacks reached only on request.
 */
@Composable
internal fun TvLoginScreen(viewModel: LoginViewModel, uiState: LoginUiState) {
    BackHandler(
        enabled = uiState.manualEntry || uiState.step == LoginStep.Credentials ||
            (uiState.step == LoginStep.Pairing && uiState.servers.size > 1)
    ) {
        when {
            uiState.step == LoginStep.Credentials -> viewModel.backToServers()
            uiState.manualEntry -> viewModel.showManualEntry(false)
            else -> viewModel.backToServers()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(horizontal = 56.dp, vertical = 36.dp)
    ) {
        when {
            uiState.step == LoginStep.Pairing && uiState.pairing != null -> TvPairing(viewModel, uiState, uiState.pairing)
            uiState.step == LoginStep.Credentials && uiState.selected != null -> TvCredentials(viewModel, uiState, uiState.selected)
            uiState.manualEntry -> TvManualEntry(viewModel, uiState)
            else -> TvServerList(viewModel, uiState)
        }
    }
}

@Composable
private fun TvHeader(subtitle: String) {
    Text(
        "Zonik",
        style = MaterialTheme.typography.displayMedium,
        color = MaterialTheme.colorScheme.primary
    )
    Spacer(Modifier.height(4.dp))
    Text(subtitle, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** Requests focus on [requester] once the element is laid out (and again when [key] changes). */
@Composable
private fun InitialFocus(requester: FocusRequester, key: Any?) {
    LaunchedEffect(key) {
        delay(80)
        runCatching { requester.requestFocus() }
    }
}

@Composable
private fun TvButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    primary: Boolean = false,
    enabled: Boolean = true,
) {
    val m = modifier.tvFocusLift(ZonikShapes.buttonShape, scale = 1.05f)
    if (primary) {
        Button(onClick = onClick, enabled = enabled, shape = ZonikShapes.buttonShape, modifier = m) { Text(text) }
    } else {
        OutlinedButton(onClick = onClick, enabled = enabled, shape = ZonikShapes.buttonShape, modifier = m) { Text(text) }
    }
}

@Composable
private fun TvServerList(viewModel: LoginViewModel, uiState: LoginUiState) {
    val firstServer = remember { FocusRequester() }
    val searchAgain = remember { FocusRequester() }
    val manual = remember { FocusRequester() }
    val target = when {
        uiState.servers.isNotEmpty() -> firstServer
        !uiState.discovering -> searchAgain
        else -> manual
    }
    InitialFocus(target, target to uiState.servers.size.coerceAtMost(1))

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        TvHeader(
            when {
                uiState.discovering && uiState.servers.isEmpty() -> "Looking for Zonik on your network…"
                uiState.servers.size > 1 -> "Choose your server"
                uiState.servers.size == 1 -> "Found on your network"
                else -> "No Zonik server found on this network"
            }
        )
        Spacer(Modifier.height(28.dp))
        if (uiState.discovering && uiState.servers.isEmpty()) {
            CircularProgressIndicator()
            Spacer(Modifier.height(28.dp))
        }
        uiState.servers.forEachIndexed { index, server ->
            TvServerRow(
                server = server,
                onClick = { viewModel.selectServer(server) },
                modifier = if (index == 0) Modifier.focusRequester(firstServer) else Modifier
            )
            Spacer(Modifier.height(12.dp))
        }
        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            TvButton(
                if (uiState.discovering) "Searching…" else "Search again",
                onClick = viewModel::startDiscovery,
                enabled = !uiState.discovering,
                modifier = Modifier.focusRequester(searchAgain)
            )
            TvButton(
                "Enter server manually",
                onClick = { viewModel.showManualEntry(true) },
                modifier = Modifier.focusRequester(manual)
            )
        }
    }
}

@Composable
private fun TvServerRow(server: DiscoveredServer, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Surface(
        onClick = onClick,
        shape = ZonikShapes.cardShape,
        color = MaterialTheme.colorScheme.surfaceContainer,
        modifier = modifier
            .widthIn(max = 640.dp)
            .fillMaxWidth()
            .tvFocusLift(ZonikShapes.cardShape, scale = 1.03f)
    ) {
        Row(Modifier.padding(horizontal = 20.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Dns, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(16.dp))
            Column {
                Text("${server.title} (${server.host})", style = MaterialTheme.typography.titleLarge)
                Text(
                    listOfNotNull(server.url, server.version?.let { "v$it" }).joinToString(" · "),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun TvManualEntry(viewModel: LoginViewModel, uiState: LoginUiState) {
    val field = remember { FocusRequester() }
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    InitialFocus(field, Unit)

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        TvHeader("Enter your server's address")
        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            value = uiState.manualUrl,
            onValueChange = viewModel::updateManualUrl,
            label = { Text("Server address") },
            placeholder = { Text("zonik, .205 or 10.0.0.205") },
            singleLine = true,
            isError = uiState.manualError != null,
            supportingText = {
                Text(uiState.manualError ?: "\"zonik\" means zonik.lan:3000; \".205\" means this network's .205 on port 3000")
            },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                autoCorrectEnabled = false,
                imeAction = ImeAction.Go
            ),
            keyboardActions = KeyboardActions(onGo = {
                keyboard?.hide()
                focusManager.clearFocus()
                viewModel.submitManualUrl()
            }),
            modifier = Modifier.widthIn(max = 640.dp).fillMaxWidth().focusRequester(field)
        )
        Spacer(Modifier.height(20.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
            TvButton(
                if (uiState.checkingManual) "Checking…" else "Connect",
                onClick = viewModel::submitManualUrl,
                primary = true,
                enabled = uiState.manualUrl.isNotBlank() && !uiState.checkingManual
            )
            TvButton("Back", onClick = { viewModel.showManualEntry(false) })
        }
    }
}

@Composable
private fun TvCredentials(viewModel: LoginViewModel, uiState: LoginUiState, server: DiscoveredServer) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        TvHeader("Sign in")
        Spacer(Modifier.height(20.dp))
        CredentialsForm(viewModel, uiState, server, modifier = Modifier.widthIn(max = 640.dp))
    }
}

@Composable
private fun TvPairing(viewModel: LoginViewModel, uiState: LoginUiState, pairing: PairingUi) {
    val newCode = remember { FocusRequester() }
    InitialFocus(newCode, pairing.server.url)
    val canChooseOther = uiState.servers.size > 1 || pairing.server.source == DiscoveredServer.Source.MANUAL

    Row(Modifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            TvHeader("Pair this TV with ${pairing.server.title} (${pairing.server.host})")
            Spacer(Modifier.height(24.dp))
            if (pairing.code == null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator()
                    Spacer(Modifier.width(16.dp))
                    Text(
                        pairing.error ?: "Getting a pairing code…",
                        style = MaterialTheme.typography.titleMedium,
                        color = if (pairing.error != null) MaterialTheme.colorScheme.error
                        else MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                Text(
                    pairing.code.chunked(3).joinToString(" "),
                    style = MaterialTheme.typography.displayLarge.copy(
                        fontSize = 112.sp,
                        lineHeight = 120.sp,
                        letterSpacing = 6.sp,
                        fontWeight = FontWeight.Bold
                    ),
                    color = MaterialTheme.colorScheme.primary
                )
                Spacer(Modifier.height(12.dp))
                Text(
                    "Scan with your phone or open ${pairHint(pairing.server)}",
                    style = MaterialTheme.typography.titleLarge
                )
                Spacer(Modifier.height(8.dp))
                val left = rememberSecondsLeft(pairing.expiresAtMs)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(10.dp))
                    Text(
                        if (left > 0) "Waiting for approval · new code in ${formatCountdown(left)}"
                        else "Getting a new code…",
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                pairing.error?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyLarge)
                }
            }
            Spacer(Modifier.height(32.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                TvButton("New code", onClick = viewModel::renewCode, modifier = Modifier.focusRequester(newCode))
                if (canChooseOther) TvButton("Other server", onClick = viewModel::backToServers)
                TvButton("Enter server manually", onClick = { viewModel.showManualEntry(true) })
                // Typing fallback, only once the user has chosen to type anyway.
                if (pairing.server.source == DiscoveredServer.Source.MANUAL) {
                    TvButton("Use password", onClick = viewModel::useCredentialsInstead)
                }
            }
        }
        pairing.approveUrl?.let {
            Spacer(Modifier.width(40.dp))
            QrImage(it, 280.dp)
        }
    }
}
