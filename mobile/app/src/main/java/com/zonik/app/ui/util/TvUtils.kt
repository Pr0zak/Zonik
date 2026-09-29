package com.zonik.app.ui.util

import android.content.Context
import android.content.pm.PackageManager
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.zonik.app.ui.theme.ZonikColors

fun Context.isTvDevice(): Boolean {
    return packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)
        || packageManager.hasSystemFeature(PackageManager.FEATURE_TELEVISION)
        || packageManager.hasSystemFeature("com.google.android.tv")
        || android.app.UiModeManager::class.java.let {
            val uiModeManager = getSystemService(Context.UI_MODE_SERVICE) as? android.app.UiModeManager
            uiModeManager?.currentModeType == android.content.res.Configuration.UI_MODE_TYPE_TELEVISION
        }
}

@Composable
fun isTv(): Boolean {
    val context = LocalContext.current
    return remember { context.isTvDevice() }
}

@Composable
fun Modifier.tvFocusHighlight(
    shape: Shape = RoundedCornerShape(8.dp)
): Modifier = composed {
    var isFocused by remember { mutableStateOf(false) }
    this.onFocusChanged { isFocused = it.isFocused }
        .then(
            if (isFocused) Modifier.border(2.dp, ZonikColors.gold, shape)
            else Modifier
        )
}

/**
 * TV focus, readable from across the room: the focused element lifts (scales up a little),
 * gains a gold ring and a soft gold glow. Neighbours do not move — the scale is a draw-time
 * transform, so nothing re-lays out when focus walks along a row.
 *
 * Put it BEFORE the element's `clickable`/focus target in the chain, like [tvFocusHighlight].
 * Wide rows want a smaller [scale] than cards: 6% of a full-width row is a lurch.
 */
@Composable
fun Modifier.tvFocusLift(
    shape: Shape = RoundedCornerShape(12.dp),
    scale: Float = 1.06f,
): Modifier = composed {
    var isFocused by remember { mutableStateOf(false) }
    val lift by androidx.compose.animation.core.animateFloatAsState(
        targetValue = if (isFocused) scale else 1f,
        animationSpec = androidx.compose.animation.core.tween(140),
        label = "tvLift"
    )
    this.onFocusChanged { isFocused = it.isFocused }
        .graphicsLayer {
            scaleX = lift
            scaleY = lift
        }
        .then(
            if (isFocused) {
                Modifier
                    .shadow(18.dp, shape, ambientColor = ZonikColors.gold, spotColor = ZonikColors.gold)
                    .border(3.dp, ZonikColors.gold, shape)
            } else {
                Modifier
            }
        )
}
