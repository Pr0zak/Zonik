package com.zonik.app.ui.util

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import com.zonik.app.ui.theme.ZonikShapes
import kotlinx.coroutines.delay

const val SIGN_OUT_TITLE = "Sign out?"
const val SIGN_OUT_MESSAGE = "Sign out of Zonik on this device? You'll need to pair again."

/**
 * Confirms signing out (which revokes this device's token). D-pad friendly: Cancel takes focus
 * first so a stray OK press on the remote does nothing harmful; both buttons show the TV focus ring.
 */
@Composable
fun SignOutConfirmDialog(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    val cancel = remember { FocusRequester() }
    LaunchedEffect(Unit) {
        delay(80)
        runCatching { cancel.requestFocus() }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(SIGN_OUT_TITLE) },
        text = { Text(SIGN_OUT_MESSAGE) },
        dismissButton = {
            TextButton(
                onClick = onDismiss,
                shape = ZonikShapes.buttonShape,
                modifier = Modifier.tvFocusLift(ZonikShapes.buttonShape, scale = 1.05f).focusRequester(cancel)
            ) { Text("Cancel") }
        },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                shape = ZonikShapes.buttonShape,
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                modifier = Modifier.tvFocusLift(ZonikShapes.buttonShape, scale = 1.05f)
            ) { Text("Sign out") }
        }
    )
}
