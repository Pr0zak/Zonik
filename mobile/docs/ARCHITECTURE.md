# Zonik Android App — Architecture

_Last updated: 2026-09-29 (app v1.31.0). This describes what the code does today; section 10 lists what is not built._

## 1. Overview

Native Android clients for a self-hosted Zonik server (OpenSubsonic API plus Zonik's own `/api`). Designed for a single user. One Gradle project, four parts:

| Module | What it is |
|---|---|
| `app/` | Phone app, Android Auto (via the media service), Google Cast sender and the Google TV UI. One APK; the TV UI is chosen at runtime. |
| `wear/` | Standalone Pixel Watch player. Streams from the server itself and does not need the phone running. |
| `core/` | Android library shared by `app` and `wear`: Subsonic Retrofit interface, auth interceptor, domain models, `md5`. No Hilt, no Room. |
| `cast/` | Not a Gradle module. `style.css` and `icon.svg`/`icon.png` for the Cast receiver's look (Styled Media Receiver classes: background, logo, splash, watermark, progress bar). |

Phone and watch share `applicationId = "com.zonik.app"`, which Wear Data Layer pairing requires.

## 2. Distribution

Sideloaded APKs, not the Play Store.

- Pushing an `app-v*` tag runs `.github/workflows/mobile-release.yml`. It restores the shared debug keystore from the `DEBUG_KEYSTORE_BASE64` secret, runs `assembleDebug`, and attaches `zonik-vX.Y.Z-debug.apk` and `zonik-wear-vX.Y.Z-debug.apk` to the GitHub release.
- Only CI-signed builds update in place. A local build is signed with a different key and needs an uninstall first.
- **In-app updates:** `UpdateChecker` reads the repo's GitHub releases, keeps only `app-v*` tags, picks the highest version's phone APK and installs it through a `FileProvider`. Phones check once at launch; TV checks from its Settings.
- **Android Auto:** a sideloaded app needs Android Auto's developer mode (tap the version 10 times) with "Unknown sources" enabled. This is a one-time setup.

## 3. Features (phone)

### 3.1 Server connection and auth
- **Login:** server URL, username and API key, checked with a raw `ping.view` call.
- **Pair with code:** `POST api/pair`, then the app polls `GET api/pair/{code}` until the server hands over a config. The TV starts this flow automatically.
- **Subsonic token auth:** `t = md5(apiKey + salt)` with a random 16-character `s` on every request, `v=1.16.1`, `c=ZonikApp` (the watch sends `c=ZonikWear`).
- **Credential storage:** Preferences DataStore (`settings`) holds URL and username as plain string keys; the API key and the Last.fm session key are encrypted with an AES-GCM key held in the Android Keystore (`core/security/CredentialCipher`, values prefixed `enc1:`). Plain values from older releases are re-saved encrypted at startup. A key that can no longer be decrypted — a backup restored onto another device — counts as signed out. The watch app does the same for its key.
- **Base URL:** Retrofit is built against a `http://localhost/` placeholder that an interceptor rewrites to the configured server. `ServerConfigCache` keeps the current config in a volatile field.
- **`CachingDns`:** tries the system resolver first. If that fails, it falls back to the last good addresses, kept for 24 h in a `dns_cache` DataStore.

### 3.2 Library and sync
- **Room database:** `zonik.db`, version 4. Entities are artists, albums, tracks and `pending_scrobbles`; the last is defined but not used.
- **Sync is always a full sync.** `SyncManager.fullSync()` pages `search3` with an empty query, 500 rows per page, separately for artists, albums and songs.
  - Starred status comes from `getStarred2`. Marked-for-deletion comes from `userRating == 1`.
  - It upserts every row, deletes local IDs the server no longer has, and keeps each row's local `offlineCached` flag.
  - A flag stops two syncs running at once.
- **Playlists** are fetched on demand, never stored in Room.
- **Background sync:** `LibrarySyncWorker` runs as periodic WorkManager work.
  - The interval comes from Settings; 0 means off, and anything else is at least 15 min.
  - The network constraint is UNMETERED when Wi-Fi-only is on, CONNECTED otherwise.
- **After a sync,** favorites can be cached offline automatically.

### 3.3 Playback
- Media3 ExoPlayer inside `ZonikMediaService`; the UI talks to it through `PlaybackManager` (section 4.2).
- **Queue:** play, play next, add to queue, shuffle toggle, repeat (off/all/one; in-app only). Queues are capped at 500 tracks.
- **Shuffle Mix (endless):** random songs tagged `endless_mix`. When 10 or fewer remain, the service appends 50 more `getRandomSongs` results that are not already queued.
  - Shuffle Mix is the same on phone, TV, Android Auto and watch.
- **Start Radio:** similar songs, falling back to the same genre, then to random.
- **Bitrate:**
  - Separate Wi-Fi/unmetered and cellular caps; defaults are original quality and 192 kbps. They are sent as `maxBitRate`; no `format` parameter is sent.
  - Optional adaptive step-down (320, 256, 192, 128, 64) after repeated buffering; it steps back up when playback is stable.
- **Playback speed:** 0.5x to 2x, cycled from Now Playing.
- **Equalizer:** `android.media.audiofx.Equalizer` on the player's audio session, set with presets or custom band levels through the `SET_EQ` session command. Settings can also open the system equalizer.
- **Waveform seek bar** (optional, off by default): 200 bars from `GET api/tracks/{id}/waveform`. If the server has none, the phone decodes the audio with `MediaExtractor`/`MediaCodec`. Results are cached in `filesDir/waveforms/`.
- **Resume:**
  - The queue, index and position are saved to DataStore on track change, every ~10 s, and when the service stops.
  - `onPlaybackResumption()` restores them for the system media card. With nothing saved, it starts a Shuffle Mix.
- **Recently played:** an in-memory list of the last 20 tracks, not persisted.

### 3.4 Caching and offline
- **Stream cache:** ExoPlayer `SimpleCache` in `cacheDir/exoplayer_audio_cache`, LRU, size from Settings (default 500 MB). The cache key is track ID plus bitrate.
  - `CacheWriter` pre-caches the next tracks: default 5 on phone, 1 on TV. It pauses while the player is buffering or offline.
- **Offline downloads:** `OfflineCacheManager` saves original-quality files to `filesDir/offline_tracks/`.
  - At most 2 downloads run at once, under a storage limit (default 2 GB).
  - Sources: the Library's Offline tab, "cache the whole queue" in Now Playing, and optional auto-cache of queues and favorites.
  - The service's data source reads these local files before touching the network.
- **Cover art:** Coil with the app's image loader. `CoverArtProvider` (`content://com.zonik.app.artwork/{id}/{size}`) serves cached art to Android Auto and system UI.

### 3.5 Find: search, catalog and downloads
- **Library search:** Subsonic `search3`, with All/Albums/Artists/Tracks filters and a top-result hero.
- **Catalog search:** `GET api/search/catalog` (optional `ai=true`, "Ask AI") returns songs, each marked **Play** if owned or **Get** if not.
- **Soulseek:** file search through `POST api/download/search`; then trigger, bulk trigger and cancel.
- **Download progress:**
  - A WebSocket to `api/ws`, reference-counted and connected only while jobs are active. It reconnects with backoff and pauses while offline.
  - A job poll (`api/jobs/*`) runs alongside it as a fallback.
  - `DownloadNotifier` posts progress and "Ready"/"Couldn't get" notifications on the `zonik_downloads` channel.
- **30 s previews:** a `preview:` item plays while the download runs. When the job completes, the real track replaces it.

### 3.6 Voice playlist (AI)
- **Where:** a mic button on the Home and Library top bars. `VoiceOverlay` is hosted once at the root.
- **Flow:** the on-device `SpeechRecognizer` produces a transcript, which goes to `POST api/assistant/voice-playlist` (`{prompt, size: 50}`).
  - Returned IDs are resolved through Room, falling back to the server, and played.
  - Songs the server says are missing can be fetched with one "Get all N" action through `api/download/trigger`.
- **States:** Listening → Curating → Picked / Missing / Getting / Failed (`VoicePlaylistManager`, a singleton).
- **Permission:** needs `RECORD_AUDIO`. The manifest declares the microphone feature as not required, so the app still installs on TVs without a mic.
- **Not available in Android Auto or on the watch.** Auto's voice search is a separate path (section 4.3).

### 3.7 User interactions
- **Star/unstar** (`star`/`unstar`).
- **Mark for deletion** is `setRating(1)`, matching the server's Flagged view. The Flagged library tab can bulk-delete through `POST api/tracks/bulk-delete`.
- **Scrobbling goes to the Zonik server only** (`scrobble.view`), from inside the media service, so Auto plays count too.
  - Now-playing (`submission=false`) is sent on each track change. The play (`submission=true`) is sent after 50% has played, checked every 5 s.
  - Failed scrobbles wait in an in-memory retry queue, lost if the process dies.
- **Neglected Gems:** `GET api/map/neglected-gems` returns owned-but-never-played tracks ranked by closeness to the user's taste.
- **Stats screen:** computed entirely from Room: counts, size, format, bitrate, genre and year distributions, top artists, most-played and recently-played albums.
- **Debug logs:**
  - `DebugLog` keeps a 500-line ring and a rolling file (512 KB plus one previous file), and records crashes synchronously.
  - URLs are logged with auth parameters redacted.
  - "Upload logs" posts them to `POST api/logs` on the server.

### 3.8 Error handling and connectivity
- **Service HTTP client:** OkHttp with a 30 s connect timeout (to wait out the server's transcode queue) and a 60 s read timeout.
- **Retry policy:**
  - A 416 clears the cache entry and retries.
  - Other 4xx errors fail.
  - DNS failures retry 3 times with growing delay.
  - Other IO errors back off exponentially up to 16 s, 10 tries.
- **Recovery:** a `ConnectivityManager` callback re-prepares the player when the network returns, if it is in error or has been stuck buffering for more than 10 s. `onPlayerError` re-prepares on IO or network errors.
- **Wake and audio:**
  - `WAKE_MODE_NETWORK` handles both the wake lock and the Wi-Fi lock; there is no manual `WifiLock`.
  - Audio focus and becoming-noisy are left to ExoPlayer (`handleAudioFocus = true`, `setHandleAudioBecomingNoisy(true)`).

### 3.9 Notifications
- **Playback:** Media3's default notification from the `MediaSession`, including the custom buttons in 4.3.
- **Channels:** `ZonikApplication` creates `zonik_downloads`; playback notifications use Media3's own channel. The unused `zonik_playback` and `zonik_sync` channels of older releases are deleted at startup.
- **Cast:** the Cast SDK posts its own notification.

### 3.10 Theming
- The app is always dark: `ZonikTheme` uses a neutral dark scheme with purple and gold accents.
- `WithAlbumScheme` builds a Material 3 scheme from the cover art with Palette. It is applied on **Home and Now Playing only**; Library, Find and Settings use the neutral scheme.

### 3.11 Permissions

| Permission | Purpose |
|---|---|
| `INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE` | Server communication, connectivity monitoring |
| `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PLAYBACK`, `WAKE_LOCK` | Background playback |
| `POST_NOTIFICATIONS` (runtime, 13+) | Download notifications |
| `MODIFY_AUDIO_SETTINGS` | Equalizer |
| `RECORD_AUDIO` (runtime) | Voice playlist mic; TV visualizer output-mix capture |
| `REQUEST_INSTALL_PACKAGES` | In-app updates |

Also declared as not required: `android.software.leanback`, `android.hardware.touchscreen` and `android.hardware.microphone`, so one APK installs on phones and TVs.

## 4. Technical Architecture

### 4.1 Layers

```
┌───────────────────────────────────────────────────────────┐
│  UI (Compose)                                             │
│  Phone: MainActivity → Login / Main pager / NowPlaying    │
│  TV:    TvMainScreen → Stage / Settings / visualizer (GL) │
├───────────────────────────────────────────────────────────┤
│  ViewModels (Hilt)            VoicePlaylistManager        │
├───────────────────────────────────────────────────────────┤
│  PlaybackManager (MediaController + CastManager)          │
├──────────────────────────────┬────────────────────────────┤
│  Repositories                │  OfflineCacheManager       │
│  Library / Settings / Sync   │  WaveformManager           │
├──────────────┬───────────────┴───────┬────────────────────┤
│ SubsonicApi  │ ZonikApi (/api)       │ Room + DataStore   │
│ (core)       │ + /api/ws WebSocket   │                    │
├──────────────┴───────────────────────┴────────────────────┤
│  ZonikMediaService (MediaLibraryService)                  │
│  ExoPlayer, SimpleCache, Android Auto tree, scrobbling    │
└───────────────────────────────────────────────────────────┘
```

DI is Hilt. The OkHttp clients are built in `di/AppModule.kt`. The main client has a 15 s connect timeout, a 30 s read timeout and a 50 MB HTTP cache; `ZonikApi` gets a 90 s read timeout.

### 4.2 Key components

#### Media service (`ZonikMediaService`)
- Extends Media3 `MediaLibraryService` and publishes a `MediaLibrarySession` for system UI, Bluetooth, Android Auto and the watch-style clients.
- **Data source chain:** offline file (`FileDataSource`), then `CacheDataSource` over `SimpleCache`, then `OkHttpDataSource`.
  - The service's OkHttp client has no auth interceptor; auth is baked into the stream URL.
- **Buffering:** 15 s minimum, 120 s maximum; playback starts after 1.5 s buffered, or 5 s after a rebuffer.
- **Queue commands:** `PLAY_TRACKS` carries IDs and metadata. Stream URIs are rebuilt from `requestMetadata.mediaUri` or from Room, because `localConfiguration` does not survive IPC. Unknown IDs keep their slot as placeholders, so the queue stays aligned.
- **Audio session:** `currentAudioSessionId` is a static field, read in-process by the TV visualizer. It is also exposed through session extras and `GET_AUDIO_SESSION`.
- **On TV,** the starred and flagged ID preload is deferred off the startup path.

#### Playback manager (`PlaybackManager`)
- A singleton holding the `MediaController`. A play request made before the controller connects waits in a single pending slot.
- Exposes `currentTrack`, `isPlaying`, `isBuffering`, `queue`, `playbackError` and `recentlyPlayed` as `StateFlow`s.
- Builds `stream.view` URLs (`estimateContentLength=true`) for Cast and queue edits, and implements the adaptive-bitrate policy.
- On a phone, restores the last queue paused after connecting. The TV skips this.
- **Cast:** when a Cast session starts it pauses local playback and loads the current queue onto the receiver through `CastManager`. The transport controls route to Cast while casting. When the session ends, playback hands back to the phone: the local player moves to the track and position the receiver had reached (`CastManager.lastKnownPositionMs`) and stays paused.

#### API clients
- **`SubsonicApi` (core):** ping, artists and albums, `search3`, `getRandomSongs`, genres, playlists, `getStarred2`, star/unstar, scrobble, `setRating`, `getSimilarSongs2`, `getSongsByGenre`, `getNowPlaying`, and more. `stream.view` and `getCoverArt.view` URLs are built by hand.
- **`ZonikApi`:** native `/api`:
  - download search, trigger, bulk and cancel
  - jobs
  - catalog search
  - pairing
  - `assistant/voice-playlist`
  - `map/neglected-gems`
  - `analysis/track/{id}` (BPM, energy and other analysis; the TV reads the tempo from it)
  - logs
  - bulk delete
- **`DownloadProgressClient`:** the `/api/ws` WebSocket.

### 4.3 Android Auto

The Auto integration is part of `ZonikMediaService`; no separate service. `automotive_app_desc.xml` is declared in the manifest.

**Browse tree.** The root tabs follow a user-reorderable setting (Settings → Devices), default order Mix, Recently Added, Library, Playlists. Browsable items use grid style and playable items list style; long lists get A–Z group headers, ignoring a leading "The".

```
Root
├── Mix
│   ├── Shuffle Mix (endless)
│   ├── Recently played → albums
│   ├── Favorites (shuffled)
│   ├── Neglected Gems
│   ├── Newly Added
│   └── Non-Favorites
├── Recently Added → 50 newest albums
├── Library
│   ├── Downloaded (shuffle downloads + A–Z tracks; plays without signal)
│   ├── Artists → Albums → Tracks
│   ├── Albums → Tracks
│   └── Genres (each plays a 100-track genre mix)
└── Playlists → Tracks
```

**Search.** `onSearch` only lists results; it never plays.
- Results are ordered: library albums, artists, tracks, then up to 5 catalog "Get: …" rows. Results are cached for 60 s.
- A "Get:" row triggers the server download and plays the 30 s preview. The service polls the job and swaps in the real track when it finishes.

**Voice "play X".** The spoken query arrives as `requestMetadata.searchQuery` (`MEDIA_PLAY_FROM_SEARCH`). It resolves in this order:
1. An empty query plays a Shuffle Mix.
2. "favorites" and similar words play starred tracks.
3. A genre name plays a genre mix.
4. Otherwise the best artist match, then the best album match, then matching tracks.
5. Failing all of those, an AI catalog search; if the song is not owned, the service downloads it and plays the preview.

**Session buttons:** Star, Mark for deletion, Shuffle, Start Radio. There is no repeat button in the session layout.

### 4.4 Navigation (phone)

```
Login (first launch / no credentials; URL + key, or pair with code)
    ↓
Main — HorizontalPager + one bottom dock (mini player over a compact nav row)
├── Home      — Shuffle Mix, Favorites / Neglected Gems / Recently Added / New Releases tiles,
│               Recently played, Recently added, voice mic
├── Library   — Tracks | Albums | Artists | Favorites | Genres | Playlists | Flagged | Offline
├── Find      — library search, catalog (Play/Get, Ask AI), Soulseek search, transfers
└── Settings  — opened from the avatar at the end of the nav row

Now Playing — overlay; opens when playback starts or from the notification
AlbumDetail (album/{id}), ArtistDetail (artist/{id}), Stats (stats) — root routes
```

On a TV device, the `main` route renders `TvMainScreen` instead of `MainScreen` (section 5).

## 5. Google TV

TV devices are detected at runtime by `isTvDevice()`: the leanback or television feature, the `com.google.android.tv` feature, or `UI_MODE_TYPE_TELEVISION`. The activity is also registered for `LEANBACK_LAUNCHER`, with a `tv_banner`. All TV UI code is in `ui/tv/`.

### 5.1 Structure

| File | Role |
|---|---|
| `TvMainScreen.kt` | The root screen and `TvViewModel`. Owns the Stage/Settings switch, the ambient timer, the remote's transport keys, and the visualizer overlay. |
| `TvStage.kt` | "The Stage": Now Playing as the root screen, the UP actions strip and the DOWN browse rails. |
| `TvVisualizerSettings.kt` | The visualizer's settings page, with a live preview and the effect gallery. |
| `DemoVisualizer.kt` | Compose wrapper around a `GLSurfaceView` that hosts `DemoRenderer`. |
| `DemoRenderer.kt` | The GL renderer: textures, offscreen buffers, transitions, audio smoothing, the Mandelbrot dive. |
| `DemoEffects.kt` | The `DemoEffect` enum: 31 fragment shaders, plus the blit and trails passes. |
| `AmbientAudio.kt` | `AmbientPulse`, `PulseAnalyzer` (FFT to bands, onsets and spectrum) and `BeatClock`. |
| `AmbientSupport.kt` | `rememberAmbientArt` (cover texture and palette), `AudioCaptureEffect`, the names of the 10 wipes, and `COVER_EFFECTS`. |
| `MandelbrotTargets.kt` | Finds random Misiurewicz points for the endless zoom. |

**`TvViewModel`** is a Hilt ViewModel over `PlaybackManager`, `LibraryRepository`, `SyncManager`, `LogUploader`, `UpdateChecker` and `SettingsRepository`. It provides:
- Mixes: Shuffle Mix (endless), shuffled Favorites, Recently added, and By release date.
- Album and playlist playback, and star.
- The data for the browse rails.
- The `tvAmbient*` DataStore settings.
- Ownership of the `audiofx.Visualizer` capture.
- On every track change, the track's BPM from `api/analysis/track/{id}`.

### 5.2 The Stage

- The whole screen is Now Playing, drawn inside a 48dp/27dp overscan margin over a radial gradient tinted from the cover.
- **Hero:** 300dp cover, title, artist and album, progress, and a transport row: Visualizer, Previous, Play/Pause, Next, Star. An "Up next" line shows below it.
  - Palette extraction runs on `Dispatchers.IO`; the main thread is where the media session handles remote commands.
- **Panels:** `StagePanel` is `NONE`, `STRIP` or `BROWSE`. The panel is drawn over the Stage and never replaces it, so playback UI and focus survive.
  - **UP** opens the actions strip: Shuffle mix, Favorites, Recently added, By year, Visualizer, Settings.
  - **DOWN** slides up the browse rails, and the hero shrinks to a compact header: Mixes, Recently played (`getAlbumList2 recent`), Recently added albums (Room), Playlists.
  - **BACK** closes the open panel.
- **With nothing playing,** the rails open by themselves and fill the screen, and BACK from them exits the app.
- **Focus:**
  - Focus follows the panel through `FocusRequester`s, retried for a few frames while the target composes.
  - `tvFocusLift` scales the focused element up and gives it a gold ring and a glow. The scale is a draw-time transform, so neighbours do not re-lay out.
- **Settings replaces the Stage full-screen:** Sync Library, Visualizer (opens its own page), Upload Logs, Check for Update, Disconnect.
  - Settings rows never use `clickable(enabled = …)`. Disabling the focused node clears focus to the root, and the remote stops working.
- **Remote keys:** the root `onPreviewKeyEvent` handles the media transport keys only, and ignores key repeats for them. D-pad keys fall through to Compose focus.

### 5.3 Ambient visualizer

- **Starting it:** from the Visualizer button, or automatically after an idle delay.
  - The idle timer arms only while music is playing, the bare Stage is showing, and neither Settings nor a panel is open.
  - Delay options: 0 (only when asked), 10 s, 30 s, 60 s, 90 s, 300 s.
- **It is an overlay drawn over the Stage,** not a replacement, so focus is exactly where it was when the user returns.
- **Keys while it is up:**
  - LEFT/RIGHT skip, OK plays or pauses, and media keys work as usual; the visuals stay up.
  - Volume and mute pass through untouched.
  - Any other key dismisses it, and that key is consumed so it does not also trigger what was focused behind.
- **Rotation:** the effects form a shuffled deck, so every enabled effect plays once before any repeats, and a new deck never opens on the effect just shown.
  - The deck advances on every track change and, optionally, on a timer: each track, 30 s, 1 min, 2 min, 5 min.
- **Track info** can be shown then faded after 10 s, always shown, or never shown.
  - For effects that draw the cover themselves (`framesCover`), the overlay drops its own cover and moves the title to the bottom.

**Audio input (`AmbientAudio.kt`)**
- **Capture:**
  - With `RECORD_AUDIO` granted, `TvViewModel` attaches `android.media.audiofx.Visualizer` to the player's session ID.
  - It uses the largest capture size at the maximum capture rate, and collects both the FFT and the waveform.
  - The permission is asked once and never insisted on. The "React to music" setting turns capture off.
- **`PulseAnalyzer`** turns each FFT frame into an `AmbientPulse`:
  - Three bands: low (~40–160 Hz), mid (~300–2000 Hz) and high (~4–12 kHz). Each is normalized to its own slowly decaying rolling peak, so quiet and loud masters move the visuals alike.
  - Envelopes have a fast attack and slow release.
  - An onset is a sharp rise in low-band energy, not a high level, so a sustained bass note does not keep firing.
  - A 64-band log-spaced spectrum (40 Hz–16 kHz) with its own per-band peaks.
  - A 256-point waveform.
- **`BeatClock`:**
  - Built from the server's stored BPM. The server knows the tempo but not where the downbeat falls, so each detected onset re-aligns the phase.
  - It knows when the next beat lands, and `anticipation()` swells over the 140 ms before it, so motion peaks on the beat.
  - With no capture at all, the renderer synthesizes a kick from the grid, so effects still move in time.

**Renderer (`DemoVisualizer` / `DemoRenderer`)**
- **Surface:** a GLES 2.0 `GLSurfaceView`, fixed at **960x540** with `setFixedSize` and scaled up by the display hardware.
  - That is a quarter of 1080p's pixels, which keeps a Chromecast with Google TV (Mali-G31) at 60 fps.
  - The view follows the lifecycle's pause/resume and preserves its EGL context.
- **One renderer per screen.** Every effect's program is compiled in `onSurfaceCreated`, so switching effects costs nothing.
- **No recomposition from music:** the UI hands over pulse, beat clock, cover, palette, title and settings through `@Volatile` fields, read at the start of each frame. Audio arrives about 20 times a second; each frame eases toward the latest values.
- **Motion integrators:** `uPhase`, `uSpin` and `uTime` are driven by bass and kick, and wrapped into 0..2 on the CPU to preserve precision over long sessions.
- **Textures:**

  | Unit | Contents |
  |---|---|
  | 0 | Cover, 256² with mirrored repeat. A palette checkerboard stands in when there is no cover. |
  | 1 | 256² tileable heightmap, built once from sines, for Voxel hills. |
  | 2 | 64x1 spectrum |
  | 3 | 256x1 waveform (synthesized from the bands when there is no capture) |
  | 4 | Track title rendered to a bitmap, for the sine scroller |
  | 5/6 | Previous frame and source buffer for feedback, trails and the blit |

- **Palette:** three colours taken from the cover. `uRainbow` blends in a classic rainbow in proportion to how grey the cover is.
- **Offscreen buffers:**
  - Each on-screen effect gets a `Slot` holding two surface-sized FBOs, previous and next, swapped every frame.
  - There are two slots, so an incoming feedback effect never overwrites the outgoing one's buffers.
  - A scratch buffer serves trails and half-resolution drawing.
- **Feedback effects** (Demo fire, Melt, Ink) read `uPrev` and draw the next frame from it.
- **Trails** can be switched on for every effect. The frame is drawn offscreen, then the trails pass `max()`es it over the previous trails frame, zoomed out slightly and faded.
- **Half-resolution effects:** `halfRes` effects (Voxel hills) draw into a quarter of the scratch buffer, and the blit scales them up.
- **Every offscreen path** reaches the screen through the blit pass, so wipes and fades still happen at full resolution.
- **Transitions:**
  - A requested effect change waits for the next kick, up to 1.5 s, then runs a 1.6 s wipe.
  - Both effects are drawn, but `wipeMask` discards each pixel from one of them before shading, so a transition costs the same as a single effect.
  - A glowing seam in the cover's colour marks the edge.
  - There are 10 wipes: block dissolve, iris, clock sweep, ragged wipe, checkerboard, diamond, spiral, venetian blinds, split doors, radiating dissolve. "Mixed" picks at random and never repeats the last one.
- **Logging:** FPS is written to `DebugLog` every 10 s.

**Effects (`DemoEffects.kt`)**

31 effects: Tunnel, Plasma, Starfield, Rotozoomer, Kaleidoscope, Metaballs, Copper bars, Synthwave, Moiré, Twister, Fire, Code rain, Crystal, Aurora, Vector balls, Julia, Mandelbrot, Shockwaves, God rays, Sunburst, Demo fire, Melt, Ink, Oscilloscope, Orbits, Neon skyline, Kaleido frame, Sine scroller, Glenz vector, Dot tunnel, Voxel hills.

- **Shader structure:** each effect is a `vec3 shade(vec2 p)` body wrapped in a shared `HEADER` and `FOOTER`.
  - `HEADER` declares all the uniforms and helpers: `pal`/`colorAt`/`vivid`/`punch` for colour, a sine-free `hash`, `withCover`/`coverDist` to frame the cover, `band()`, `wave()`, `titleAt()`, `prevAt()`, `roam()`, `fastAtan2`, `tri`, `rot`. It uses highp where the GPU supports it.
  - `FOOTER` holds `wipeMask` and `main()`, which applies the centre wander, the wipe discard and seam, and the fade.
- **Flags:**
  - `framesCover`: the effect draws the cover dead centre (Shockwaves, God rays, Sunburst, Melt, Oscilloscope, Orbits, Kaleido frame).
  - `feedback`: the effect reads its previous frame (see above).
  - `halfRes`: drawn at half resolution (Voxel hills).
  - `COVER_EFFECTS` (Tunnel, Rotozoomer, Kaleidoscope) are built from the cover image itself; the rest take only its colours.
- **Budget:** set by the Mali-G31: closed-form maths per pixel, at most three texture reads, no raymarching, only short loops. The CPU precomputes whatever is the same for every pixel: metaball paths, dot-tunnel rings, shockwave ages, the kaleidoscope's segment count (which changes every 16 kicks).
- **The wrap-at-2 rule:** because `uPhase`, `uSpin` and `uTime` wrap at 2, every effect must use them only in ways that repeat with period 2: as a mirrored texture coordinate, through `fract(x * k / 2)`, or through `sin(πk·x)` with integer `k`. Otherwise the wrap shows as a jump.

**Mandelbrot dive (`MandelbrotTargets.kt` + renderer)**
- **Targets:** each time the effect comes on screen, it picks a random **Misiurewicz point** by Newton's method on `f^(pre+per)(0) − f^pre(0)`.
  - Preperiod is 2–6 and period 1–3.
  - The point is checked for exact preperiod and period and must lie off the real axis.
  - The multiplier |λ| must be between 2.2 and 40.
  - The fallback is a known seahorse-valley point.
- **Endless zoom:**
  - The set around such a point is asymptotically self-similar. The dive runs from the whole set down to scale 2e-5, then loops one self-similarity step: scale ÷ |λ|, turned by arg λ. The zoom never ends, and the per-pixel cost never grows.
  - Bass and kick speed up the dive.
  - About every 150 s it cuts to a new point through a white flash, timed to a kick.
- **fp32 rendering:**
  - Uses perturbation against the point's exact orbit: the preperiod, then the cycle repeating forever.
  - A CPU series-approximation skip (ε ≈ A·δ) pre-runs the iterations that are the same for every pixel, leaving at most 32 in the shader.
  - Colouring uses smooth escape bands plus a distance-estimate glow on the filaments.

**Visualizer settings page (`TvVisualizerSettings`)**
- Laid out for a 960x540dp canvas with no scrolling.
- **Left column:** rows that each cycle on OK: Visualizer on/off, Start after, React to music, Change effect, Track info, Transitions (Mixed or one fixed wipe), Trails.
- **Right column:** a live 16:9 preview of the focused effect, using the current track's pulse and art.
- **Below:** an 8-per-row gallery of every effect. OK adds an effect to the rotation or removes it; the last one can't be removed. There are also "All" and "No cover art" shortcuts.
- **Card styling:** effects in the rotation wear the purple gradient. Gold marks focus only.
- All values persist in DataStore (`tvAmbient*`).

## 6. Wear OS

`wear/` is a separate APK: minSdk 30, standalone. It depends on `:core` and has no Hilt and no Room; `WearApp` and `WearNetwork` wire it together by hand.

- **Playback:**
  - `ZonikWearMediaService` is its own Media3 `MediaLibraryService` with ExoPlayer and a 200 MB `SimpleCache`.
  - Its browse tree: recent albums, library (artists → albums → tracks), playlists.
- **UI connection:** `WearMediaManager` binds the UI to the service through a media controller with reconnect.
- **Quick Mix:** `EndlessMix` tags queued items. When 10 or fewer remain, the service appends 50 more random songs.
- **Pairing:**
  - **Phone push:** Settings → Devices → Set up Wear OS watch sends `{url, username, apiKey}` over `MessageClient` on path `/zonik/pair`; `PairingDataListener` receives it.
  - **On the watch:** the code flow through `api/pair`.
  - The config is stored in the `wear_settings` DataStore.
- **Screens:**
  - UI is Wear Compose Material 3, with every screen inside `ScreenScaffold`.
  - Now Playing: progress ring, rotary seek of ±5 s with haptics, Quick Mix.
  - Queue.
  - Settings: re-pair, clear cache.
- **Surfaces:** `NowPlayingTileService` and `TrackComplicationService` (short text, long text, ranged value) refresh every 30 s through a `SessionToken`.
- **Network:**
  - `NetworkMonitor` counts only direct Wi-Fi or cellular as online; Bluetooth through the phone does not count.
  - `ConnectionBanner` shows "Connecting…" or "Player offline".
- **Scrobbling** works the same as on the phone, with `c=ZonikWear`, so the server can tell the watch's plays apart.

## 7. Dependencies

| Library | Version | Purpose |
|---|---|---|
| AGP / Kotlin / KSP | 8.7.3 / 2.1.0 | Build (app: compileSdk/targetSdk 35, minSdk 26) |
| AndroidX Media3 (ExoPlayer, Session, OkHttp datasource) | 1.5.1 | Playback, MediaSession, Android Auto |
| Compose BOM + Material 3 | 2024.12.01 | UI (phone and TV) |
| Retrofit + OkHttp + Kotlinx Serialization | — | HTTP, WebSocket, JSON |
| Room | 2.6.1 | Local library |
| Hilt (+ hilt-work) | 2.53.1 | DI (app only) |
| Coil | 2.7.0 | Image loading |
| Compose Navigation | — | Phone routes |
| AndroidX Palette | — | Cover colours (phone scheme, TV tint and visualizer palette) |
| DataStore Preferences | — | Settings, credentials, resume state, TV visualizer settings |
| WorkManager | — | Periodic library sync |
| Google Cast + MediaRouter | 21.5.0 | Chromecast sender |
| Play Services Wearable | 18.2.0 | Phone → watch pairing |
| OpenGL ES 2.0 (platform) | — | TV visualizer |
| Wear Compose Material 3, Horologist, Tiles | 1.6.1 / 0.6.20 / 1.4.1 | Watch UI |
| Paparazzi | 1.3.5 | JVM screenshot tests (`app/src/test/.../screenshots`) |

Paging 3 (`paging-runtime`, `paging-compose`, `room-paging`) and AndroidX Browser are declared in `app/build.gradle.kts` but not used.

## 8. Screens — UI summary (phone)

### Login
- Server URL, Username, API Key fields, validated with `ping`.
- "Pair with code" as an alternative.

### Home
- The album-art colour scheme, from the featured cover.
- A Shuffle Mix tile, and quick tiles for Favorites, Neglected Gems, Recently Added and New Releases.
- "Recently played" and "Recently added" rows.
- A sync banner and the voice mic.

### Library
- Tabs: Tracks, Albums, Artists, Favorites, Genres, Playlists, Flagged, Offline.
- Sorting:
  - Tracks: title, artist, album, duration, recently added.
  - Albums: name, artist, year, recently added.
- A–Z fast-scroll bar and the voice mic.
- Album Detail and Artist Detail are separate routes.

### Find
- **Library search:** All/Albums/Artists/Tracks filters and a top-result hero.
- **Catalog:** songs marked Play or Get, and Ask AI.
- **Soulseek:** results with format and bitrate, single or bulk Get.
- **Transfers:** active transfers with cancel and live progress, recent history, and a "Soulseek offline" banner.

### Now Playing
- The album-art colour scheme.
- Cover, title and artist, and a seek bar that can show the waveform.
- Shuffle, previous, play/pause, next and repeat; star; Start Radio; speed; a Cast button.
- A queue panel with per-track offline state and "cache the whole queue".

### Mini player
- Lives in the bottom dock above the nav row and hides when nothing is loaded.
- Tapping it opens Now Playing.

### Stats
- Library totals and distributions, top artists, and most-played and recently-played albums, all from Room.

### Settings
- **Server:** address, username, password or API key, test connection, disconnect.
- **Playback:** quality on Wi-Fi and on mobile data, adaptive quality, preload upcoming tracks, waveform seek bar, keep screen on.
- **Equalizer:** in-app presets and bands, or the system equalizer.
- **Library:** library statistics, automatic sync interval, only on Wi-Fi.
- **Offline downloads:** download the queue, download favorites, storage limit, delete downloads.
- **Storage:** streaming cache and artwork cache, with clear buttons.
- **Devices:** set up Wear OS watch (Send), Android Auto tabs.
- **About:** version and update, source code link.
- **Troubleshooting:** send logs to server, copy logs, clear logs.

## 9. Implemented features (v1.31.0)
- **Library sync:** full sync through `search3` paging, with background WorkManager sync.
- **Playback:** streaming with a disk cache, read-ahead pre-caching, offline downloads, and adaptive and network-aware bitrate.
- **Mixes:** endless Shuffle Mix on phone, TV, Auto and watch; Start Radio; Neglected Gems.
- **Find:** library, catalog (Play/Get, Ask AI) and Soulseek search, with WebSocket progress and 30 s previews while a download runs.
- **Voice:** AI voice playlists from the mic, with one-tap Get for missing songs.
- **Android Auto:** a reorderable 4-tab browse tree, search with catalog Get, voice play-from-search, and custom session buttons.
- **Chromecast** sender with a styled receiver.
- **Equalizer,** playback speed, and the waveform seek bar.
- **Google TV:** the Stage, and the GPU visualizer with 31 effects, beat sync, trails and 10 wipes.
- **Standalone Pixel Watch player** with a tile, a complication, and phone-push pairing.
- **Operations:** self-update from GitHub releases, log upload to the server, code pairing, and Paparazzi screenshot tests.

## 10. Not implemented / future
- Last.fm scrobbling. Only unused `scrobblingEnabled` and `lastFmSessionKey` settings keys exist.
- Crossfade, ReplayGain or normalization, skip silence, sleep timer.
- Lyrics (OpenSubsonic `getLyricsBySongId`).
- Incremental sync; storing playlists in Room; persistent offline scrobble queue (the `pending_scrobbles` table is unused).
- Paging 3.
- Voice playlists in Android Auto or on the watch.
- Queue drag-to-reorder; smart playlists; playlist import/export.
