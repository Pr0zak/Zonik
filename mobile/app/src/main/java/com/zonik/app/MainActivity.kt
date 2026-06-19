package com.zonik.app

import android.content.Intent
import com.zonik.app.ui.util.isTvDevice
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.zonik.app.data.repository.SettingsRepository
import com.zonik.app.data.repository.SyncManager
import com.zonik.app.media.PlaybackManager
import com.zonik.app.ui.components.MiniPlayerRow
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import com.zonik.app.ui.navigation.MainTab
import com.zonik.app.ui.navigation.Screen
import com.zonik.app.ui.screens.home.HomeScreen
import com.zonik.app.ui.screens.library.AlbumDetailScreen
import com.zonik.app.ui.screens.library.ArtistDetailScreen
import com.zonik.app.ui.screens.library.LibraryScreen
import com.zonik.app.ui.screens.library.LibraryTab
import com.zonik.app.ui.screens.login.LoginScreen
import com.zonik.app.ui.screens.nowplaying.NowPlayingScreen
import com.zonik.app.ui.screens.playlists.PlaylistsScreen
import com.zonik.app.ui.screens.search.SearchScreen
import com.zonik.app.ui.screens.settings.SettingsScreen
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import com.zonik.app.ui.theme.ZonikShapes
import com.zonik.app.ui.util.isTv
import kotlinx.coroutines.launch
import com.zonik.app.ui.theme.ZonikTheme
import androidx.compose.foundation.focusGroup
import dagger.hilt.android.AndroidEntryPoint
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import com.zonik.app.data.api.UpdateChecker
import com.zonik.app.data.api.AppUpdate
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class MainViewModel @Inject constructor(
    settingsRepository: SettingsRepository,
    private val playbackManager: PlaybackManager,
    private val syncManager: SyncManager,
    private val updateChecker: UpdateChecker
) : ViewModel() {

    val isLoggedIn = settingsRepository.isLoggedIn
        .stateIn(viewModelScope, SharingStarted.Eagerly, null as Boolean?)

    val syncState = syncManager.syncState

    // Emits when playTracks is called (for auto-showing Now Playing immediately)
    val playbackStarted: Flow<Unit> = playbackManager.playbackRequested

    private val _availableUpdate = MutableStateFlow<AppUpdate?>(null)
    val availableUpdate: StateFlow<AppUpdate?> = _availableUpdate.asStateFlow()

    private val _updateProgress = MutableStateFlow<Float?>(null)
    val updateProgress: StateFlow<Float?> = _updateProgress.asStateFlow()

    @Volatile private var updateChecked = false

    init {
        viewModelScope.launch {
            playbackManager.connect()
        }
        // Sync is manual or scheduled — no auto-sync on startup
    }

    fun syncNow() {
        viewModelScope.launch { syncManager.fullSync() }
    }

    /** Checks GitHub for a newer release exactly once per process (on phone launch). */
    fun checkForUpdateOnce() {
        if (updateChecked) return
        updateChecked = true
        viewModelScope.launch {
            _availableUpdate.value = updateChecker.checkForUpdate()
        }
    }

    fun downloadUpdate() {
        val update = _availableUpdate.value ?: return
        viewModelScope.launch {
            _updateProgress.value = 0f
            val ok = updateChecker.downloadAndInstall(update) { _updateProgress.value = it }
            if (!ok) _updateProgress.value = null
        }
    }

    fun dismissUpdate() {
        _availableUpdate.value = null
    }
}

@AndroidEntryPoint
class MainActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_SHOW_NOW_PLAYING = "SHOW_NOW_PLAYING"
    }

    // Mutable state to signal that Now Playing should be shown
    internal val showNowPlayingFromIntent = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        handleNowPlayingIntent(intent)
        setContent {
            ZonikTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    ZonikApp(showNowPlayingFromIntent = showNowPlayingFromIntent)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleNowPlayingIntent(intent)
    }

    @javax.inject.Inject lateinit var playbackManager: com.zonik.app.media.PlaybackManager

    override fun onStop() {
        super.onStop()
        // On TV, stop playback when app goes to background (no background music on TV)
        if (isTvDevice() && !isChangingConfigurations) {
            if (playbackManager.isPlaying.value) {
                playbackManager.togglePlayPause()
            }
        }
    }

    override fun onDestroy() {
        // On TV, fully stop service
        if (isTvDevice()) {
            stopService(android.content.Intent(this, com.zonik.app.media.ZonikMediaService::class.java))
        }
        super.onDestroy()
    }

    private fun handleNowPlayingIntent(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_SHOW_NOW_PLAYING, false) == true) {
            showNowPlayingFromIntent.value = true
        }
    }
}

@Composable
fun ZonikApp(
    viewModel: MainViewModel = hiltViewModel(),
    showNowPlayingFromIntent: MutableState<Boolean> = mutableStateOf(false)
) {
    val rootNavController = rememberNavController()
    val isLoggedIn by viewModel.isLoggedIn.collectAsState()
    var showNowPlaying by remember { mutableStateOf(false) }

    // Wait until login state is determined from DataStore
    if (isLoggedIn == null) return

    // Auto-show Now Playing when a track starts playing (not on TV — TV has playback bar)
    val syncState by viewModel.syncState.collectAsState()
    val isTvDevice = isTv()
    LaunchedEffect(Unit) {
        viewModel.playbackStarted.collect {
            if (!isTvDevice) showNowPlaying = true
        }
    }

    // Show Now Playing when opened from notification
    val intentShowNowPlaying by showNowPlayingFromIntent
    LaunchedEffect(intentShowNowPlaying) {
        if (intentShowNowPlaying) {
            showNowPlaying = true
            showNowPlayingFromIntent.value = false
        }
    }

    // Check GitHub for an app update once on launch (phone only — TV self-checks).
    LaunchedEffect(isLoggedIn, isTvDevice) {
        if (isLoggedIn == true && !isTvDevice) viewModel.checkForUpdateOnce()
    }

    val startDestination = if (isLoggedIn == true) Screen.Main.route else Screen.Login.route

    Box(modifier = Modifier.fillMaxSize()) {
        NavHost(
            navController = rootNavController,
            startDestination = startDestination
        ) {
            composable(Screen.Login.route) {
                LoginScreen(
                    onLoginSuccess = {
                        rootNavController.navigate(Screen.Main.route) {
                            popUpTo(Screen.Login.route) { inclusive = true }
                        }
                    }
                )
            }
            composable(Screen.Main.route) {
                if (isTv()) {
                    com.zonik.app.ui.tv.TvMainScreen(
                        onNavigateToAlbum = { albumId ->
                            rootNavController.navigate(Screen.AlbumDetail.createRoute(albumId))
                        },
                        onDisconnected = {
                            rootNavController.navigate(Screen.Login.route) {
                                popUpTo(0) { inclusive = true }
                            }
                        }
                    )
                } else {
                    MainScreen(
                        rootNavController = rootNavController,
                        onExpandNowPlaying = { showNowPlaying = true }
                    )
                }
            }
            composable(
                route = Screen.AlbumDetail.route,
                arguments = listOf(navArgument("albumId") { type = NavType.StringType })
            ) {
                AlbumDetailScreen(
                    onNavigateBack = { rootNavController.popBackStack() },
                    onNavigateToArtist = { artistId ->
                        rootNavController.navigate(Screen.ArtistDetail.createRoute(artistId))
                    }
                )
            }
            composable(
                route = Screen.ArtistDetail.route,
                arguments = listOf(navArgument("artistId") { type = NavType.StringType })
            ) {
                ArtistDetailScreen(
                    onNavigateBack = { rootNavController.popBackStack() },
                    onNavigateToAlbum = { albumId ->
                        rootNavController.navigate(Screen.AlbumDetail.createRoute(albumId))
                    }
                )
            }
            composable(Screen.Stats.route) {
                com.zonik.app.ui.screens.stats.StatsScreen(
                    onBack = { rootNavController.popBackStack() }
                )
            }
        }

        if (!isTvDevice) {
            AnimatedVisibility(
                visible = showNowPlaying,
                enter = slideInVertically(
                    initialOffsetY = { it },
                    animationSpec = tween(250)
                ),
                exit = slideOutVertically(
                    targetOffsetY = { it },
                    animationSpec = tween(200)
                )
            ) {
                NowPlayingScreen(onBack = { showNowPlaying = false })
            }
        }

        // Launch-time update prompt (phone only; TV self-checks in TvMainScreen).
        UpdatePrompt(viewModel = viewModel, isTv = isTvDevice)
    }
}

/** One-shot "Update available" dialog shown on phone launch when a newer release exists. */
@Composable
private fun UpdatePrompt(viewModel: MainViewModel, isTv: Boolean) {
    if (isTv) return
    val update by viewModel.availableUpdate.collectAsState()
    val progress by viewModel.updateProgress.collectAsState()
    val current = update ?: return

    AlertDialog(
        onDismissRequest = { if (progress == null) viewModel.dismissUpdate() },
        icon = {
            Icon(
                imageVector = Icons.Filled.NewReleases,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary
            )
        },
        title = { Text("Update available: v${current.version}") },
        text = {
            Column {
                if (current.releaseNotes.isNotBlank()) {
                    Text(
                        text = current.releaseNotes,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 8,
                        overflow = TextOverflow.Ellipsis
                    )
                }
                val p = progress
                if (p != null) {
                    Spacer(Modifier.height(12.dp))
                    LinearProgressIndicator(
                        progress = { p },
                        modifier = Modifier.fillMaxWidth()
                    )
                    Text(
                        text = "${(p * 100).toInt()}%",
                        style = MaterialTheme.typography.labelSmall
                    )
                }
            }
        },
        confirmButton = {
            if (progress == null) {
                TextButton(onClick = { viewModel.downloadUpdate() }) { Text("Update now") }
            }
        },
        dismissButton = {
            if (progress == null) {
                TextButton(onClick = { viewModel.dismissUpdate() }) { Text("Later") }
            }
        }
    )
}

private data class TabItem(
    val tab: MainTab,
    val icon: ImageVector,
    val label: String
)

private val tabs = listOf(
    TabItem(MainTab.Home, Icons.Filled.Home, MainTab.Home.label),
    TabItem(MainTab.Library, Icons.Filled.LibraryMusic, MainTab.Library.label),
    TabItem(MainTab.Search, Icons.Filled.Search, MainTab.Search.label),
    TabItem(MainTab.Settings, Icons.Filled.Settings, MainTab.Settings.label)
)

/**
 * Compact bottom navigation row used on phone/tablet inside the unified dock.
 * ~58dp tall (vs. Material NavigationBar's 80dp): three primary tabs plus a
 * circular profile avatar that opens Settings (Option B graft).
 */
@Composable
private fun CompactNavRow(
    primaryTabs: List<TabItem>,
    selectedIndex: Int,
    settingsSelected: Boolean,
    onSelectTab: (Int) -> Unit,
    onOpenSettings: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(58.dp)
            .focusGroup(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        primaryTabs.forEachIndexed { index, tab ->
            CompactNavItem(
                icon = tab.icon,
                label = tab.label,
                selected = index == selectedIndex,
                onClick = { onSelectTab(index) },
                modifier = Modifier.weight(1f)
            )
        }
        ProfileNavItem(
            selected = settingsSelected,
            onClick = onOpenSettings,
            modifier = Modifier.weight(1f)
        )
    }
}

@Composable
private fun CompactNavItem(
    icon: ImageVector,
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val tint = if (selected) MaterialTheme.colorScheme.primary
    else MaterialTheme.colorScheme.onSurfaceVariant
    Column(
        modifier = modifier
            .fillMaxHeight()
            .clip(RoundedCornerShape(16.dp))
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier
                .widthIn(min = 44.dp)
                .height(26.dp)
                .clip(RoundedCornerShape(percent = 50))
                .background(
                    if (selected) MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                    else Color.Transparent
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = tint,
                modifier = Modifier.size(20.dp)
            )
        }
        Spacer(Modifier.height(2.dp))
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = tint,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
private fun ProfileNavItem(
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val labelColor = if (selected) MaterialTheme.colorScheme.primary
    else MaterialTheme.colorScheme.onSurfaceVariant
    Column(
        modifier = modifier
            .fillMaxHeight()
            .clip(RoundedCornerShape(16.dp))
            .clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Box(
            modifier = Modifier.height(26.dp),
            contentAlignment = Alignment.Center
        ) {
            Surface(
                shape = CircleShape,
                color = if (selected) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.surfaceContainerHighest,
                modifier = Modifier.size(24.dp)
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(
                        imageVector = Icons.Filled.Person,
                        contentDescription = null,
                        tint = if (selected) MaterialTheme.colorScheme.onPrimary
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(15.dp)
                    )
                }
            }
            // Tiny gear badge signalling this opens Settings.
            Surface(
                shape = CircleShape,
                color = MaterialTheme.colorScheme.surfaceContainerHighest,
                modifier = Modifier
                    .size(13.dp)
                    .align(Alignment.BottomEnd)
            ) {
                Icon(
                    imageVector = Icons.Filled.Settings,
                    contentDescription = null,
                    tint = labelColor,
                    modifier = Modifier.padding(2.dp)
                )
            }
        }
        Spacer(Modifier.height(2.dp))
        Text(
            text = "Settings",
            style = MaterialTheme.typography.labelMedium,
            color = labelColor,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

@Composable
fun MainScreen(
    rootNavController: NavHostController,
    onExpandNowPlaying: () -> Unit
) {
    val pagerState = rememberPagerState(pageCount = { tabs.size })
    val coroutineScope = rememberCoroutineScope()
    val isTv = isTv()

    // The unified bottom dock measures its own height (onSizeChanged) so content
    // padding adapts to mini-player visibility, font scale, and gesture insets —
    // no hardcoded magic numbers that desync from the real bars.
    val density = LocalDensity.current
    var dockHeightPx by remember { mutableIntStateOf(0) }
    val dockHeight = with(density) { dockHeightPx.toDp() }

    // TV uses simple tab index, phone uses pager
    var tvSelectedTab by remember { mutableIntStateOf(0) }
    val currentPage = if (isTv) tvSelectedTab else pagerState.currentPage

    var requestedLibraryTab by remember { mutableStateOf<LibraryTab?>(null) }

    fun goToLibrary(tab: LibraryTab? = null) {
        requestedLibraryTab = tab
        if (isTv) tvSelectedTab = 1
        else coroutineScope.launch { pagerState.animateScrollToPage(1) }
    }

    // Screen content lambda (shared between TV and phone)
    @Composable
    fun TabContent(page: Int) {
        when (page) {
            0 -> HomeScreen(
                onNavigateToLibraryTracks = { goToLibrary(LibraryTab.TRACKS) },
                onNavigateToLibraryFavorites = { goToLibrary(LibraryTab.FAVORITES) },
                onNavigateToAlbum = { albumId ->
                    rootNavController.navigate(Screen.AlbumDetail.createRoute(albumId))
                }
            )
            1 -> LibraryScreen(
                onNavigateToAlbum = { albumId ->
                    rootNavController.navigate(Screen.AlbumDetail.createRoute(albumId))
                },
                onNavigateToArtist = { artistId ->
                    rootNavController.navigate(Screen.ArtistDetail.createRoute(artistId))
                },
                requestedTab = requestedLibraryTab,
                onTabConsumed = { requestedLibraryTab = null }
            )
            2 -> SearchScreen(
                onNavigateToAlbum = { albumId ->
                    rootNavController.navigate(Screen.AlbumDetail.createRoute(albumId))
                },
                onNavigateToArtist = { artistId ->
                    rootNavController.navigate(Screen.ArtistDetail.createRoute(artistId))
                }
            )
            3 -> SettingsScreen(
                onDisconnected = {
                    rootNavController.navigate(Screen.Login.route) {
                        popUpTo(0) { inclusive = true }
                    }
                },
                onNavigateToStats = {
                    rootNavController.navigate(Screen.Stats.route)
                }
            )
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        val contentModifier = Modifier
            .fillMaxSize()
            .padding(bottom = dockHeight)

        // Content area
        if (isTv) {
            // TV: direct rendering, no pager animation
            Box(modifier = contentModifier) {
                TabContent(tvSelectedTab)
            }
        } else {
            // Phone: swipeable HorizontalPager
            HorizontalPager(
                state = pagerState,
                modifier = contentModifier,
                beyondViewportPageCount = 1
            ) { page ->
                TabContent(page)
            }
        }

        // Unified Now-Playing Dock: the mini-player and the nav tabs share ONE
        // glass surface (rounded top, single elevation, no gap). The dock owns
        // the navigation-bar / IME insets; content padding is measured from it.
        Surface(
            color = MaterialTheme.colorScheme.surfaceContainerHigh,
            shape = ZonikShapes.navBarShape,
            tonalElevation = 0.dp,
            shadowElevation = 8.dp,
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .imePadding()
                .onSizeChanged { dockHeightPx = it.height }
        ) {
            Column(modifier = Modifier.navigationBarsPadding()) {
                // Now-playing row — renders nothing when no track is loaded, so
                // the dock collapses to just the nav bar (no reserved dead space).
                MiniPlayerRow(onClick = onExpandNowPlaying)

                if (isTv) {
                    // TV keeps the full focusable Material nav bar (all four tabs).
                    NavigationBar(
                        containerColor = Color.Transparent,
                        tonalElevation = 0.dp,
                        windowInsets = WindowInsets(0, 0, 0, 0),
                        modifier = Modifier.focusGroup()
                    ) {
                        tabs.forEachIndexed { index, tabItem ->
                            NavigationBarItem(
                                icon = {
                                    Icon(
                                        imageVector = tabItem.icon,
                                        contentDescription = null
                                    )
                                },
                                label = {
                                    Text(
                                        text = tabItem.label,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        style = MaterialTheme.typography.labelMedium
                                    )
                                },
                                selected = currentPage == index,
                                onClick = { tvSelectedTab = index },
                                colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = MaterialTheme.colorScheme.primary,
                                    selectedTextColor = MaterialTheme.colorScheme.primary,
                                    unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                    unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                                    indicatorColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                                )
                            )
                        }
                    }
                } else {
                    // Phone: compact ~58dp nav row — 3 primary tabs + Settings as a
                    // profile avatar (Option B graft), shrinking the dock toward ~118dp.
                    CompactNavRow(
                        primaryTabs = tabs.take(3),
                        selectedIndex = currentPage,
                        settingsSelected = currentPage == 3,
                        onSelectTab = { index ->
                            coroutineScope.launch { pagerState.animateScrollToPage(index) }
                        },
                        onOpenSettings = {
                            coroutineScope.launch { pagerState.animateScrollToPage(3) }
                        }
                    )
                }
            }
        }
    }
}
