<p align="center">
  <img src="docs/logo.svg" alt="Zonik" width="320">
</p>

<p align="center">
  Self-hosted music backend with OpenSubsonic API.<br>
  Track-focused library management with smart discovery, Soulseek downloads, audio analysis, and AI-powered recommendations.
</p>

<p align="center">
  Includes a native Android app — phone, Android Auto, Google TV and a Pixel Watch companion — under <a href="mobile/"><code>mobile/</code></a>.
</p>

## Screenshots

### Web

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="Dashboard" width="48%">
  <img src="docs/screenshots/discover.png" alt="Discover" width="48%">
</p>
<p align="center">
  <img src="docs/screenshots/library.png" alt="Library" width="48%">
  <img src="docs/screenshots/map.png" alt="Music Map" width="48%">
</p>
<p align="center">
  <img src="docs/screenshots/downloads.png" alt="Downloads" width="48%">
  <img src="docs/screenshots/stats.png" alt="Stats" width="48%">
</p>

### Android

<p align="center">
  <img src="docs/screenshots/phone-home.png" alt="Home" width="23%">
  <img src="docs/screenshots/phone-nowplaying.png" alt="Now Playing" width="23%">
  <img src="docs/screenshots/phone-library.png" alt="Library — tracks" width="23%">
  <img src="docs/screenshots/phone-albums.png" alt="Library — albums" width="23%">
</p>

### Google TV

Now Playing is the whole screen. UP opens the actions strip, DOWN slides the browse rails up while the music keeps playing.

<p align="center">
  <img src="docs/screenshots/tv-stage.png" alt="The Stage — Now Playing" width="48%">
  <img src="docs/screenshots/tv-browse.png" alt="Browse rails" width="48%">
</p>
<p align="center">
  <img src="docs/screenshots/tv-strip.png" alt="UP actions strip" width="48%">
  <img src="docs/screenshots/tv-visualizer-settings.png" alt="Visualizer settings with live preview" width="48%">
</p>

Left idle, the TV turns into a demo-scene visualizer: 31 GPU shader effects that react to the music (bass, mids, highs, beats and a 64-band spectrum), coloured from the album art, switching with beat-synced wipes.

<p align="center">
  <img src="docs/screenshots/tv-fx-sunburst.jpg" alt="Sunburst" width="24%">
  <img src="docs/screenshots/tv-fx-tunnel.jpg" alt="Tunnel" width="24%">
  <img src="docs/screenshots/tv-fx-synthwave.jpg" alt="Synthwave" width="24%">
  <img src="docs/screenshots/tv-fx-shockwaves.jpg" alt="Shockwaves" width="24%">
</p>
<p align="center">
  <img src="docs/screenshots/tv-fx-melt.jpg" alt="Melt" width="24%">
  <img src="docs/screenshots/tv-fx-fire.jpg" alt="Fire" width="24%">
  <img src="docs/screenshots/tv-fx-skyline.jpg" alt="Neon skyline" width="24%">
  <img src="docs/screenshots/tv-fx-crystal.jpg" alt="Crystal" width="24%">
</p>

## Features

- **OpenSubsonic API** - Full Subsonic/OpenSubsonic implementation for the included mobile app and any Subsonic client
- **Track-focused** - Download individual tracks, not full discographies
- **Native Soulseek client** - Built-in P2P client with multi-strategy search and quality scoring
- **Last.fm integration** - Discovery, scrobbling, loved track sync, similar artists/tracks
- **Audio analysis** - BPM, key, energy, danceability via Essentia
- **Vibe embeddings** - CLAP-based 512-dim audio embeddings for similarity search
- **AI recommendations** - Claude-powered taste profiling, playlist curation, and track suggestions
- **Playlist discovery** - Find and import playlists from Spotify/Deezer, preview tracks, download missing
- **Echo Match** - Find tracks with similar vibes using audio embeddings
- **Remix discovery** - Find remixes, edits, and versions of library tracks via Last.fm
- **Track upgrades** - Automatically find and replace low-quality tracks with better versions
- **Stream transcoding** - On-the-fly ffmpeg transcoding (FLAC to MP3/OGG/Opus)
- **Scheduled tasks** - Automated library scan, enrichment, discovery, playlist generation
- **Modern web UI** - SvelteKit 5 + Tailwind CSS dark theme with 16 routes

## Architecture

```
FastAPI (backend) ─── SQLite (WAL+FTS5) ─── ARQ + Redis (workers)
     │                                             │
SvelteKit (frontend)                         Background tasks:
     │                                        - Soulseek downloads
OpenSubsonic API ──┬── mobile/app (Android phone, Auto, TV)
     │             ├── mobile/wear (Pixel Watch — standalone)
     │             └── any Subsonic client      - Audio analysis (Essentia)
     ├── Native Soulseek P2P                    - Vibe embeddings (CLAP)
     ├── Last.fm API                            - AI recommendations
     ├── Spotify / Deezer APIs                  - Discovery & enrichment
     └── Claude API (AI features)               - Scheduled jobs
```

## Quick Start

### Development

```bash
# Backend
uv venv && uv pip install -e .
cp zonik.toml.example zonik.toml  # Edit with your settings
uv run uvicorn backend.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Worker (requires Redis)
uv run arq backend.workers.WorkerSettings
```

### Production (Proxmox LXC)

```bash
# Run on your Proxmox host — creates the CT, installs everything, starts services:
bash <(curl -sL https://raw.githubusercontent.com/Pr0zak/Zonik/main/create-ct.sh)
```

See [Installation Guide](docs/installation.md) for details.

## Configuration

Edit `zonik.toml` (or `/etc/zonik/zonik.toml` in production):

```toml
[library]
music_dir = "/music"

[soulseek]
username = "your-username"
password = "your-password"

[lastfm]
api_key = "your-key"
write_api_key = "your-key"
write_api_secret = "your-secret"
```

See [Configuration Reference](docs/configuration.md) for all options.

## Subsonic API

Point the bundled mobile app (or any Subsonic client) at `http://<host>:3000/rest` with credentials `admin` / `admin`.

Supported endpoints: ping, getLicense, getArtists, getArtist, getAlbum, getSong, getAlbumList2, search3, stream, download, getCoverArt, star, unstar, scrobble, getPlaylists, createPlaylist, getBookmarks, savePlayQueue, and more.

See [API Reference](docs/api.md) for the full list.

## Mobile (Android phone, Google TV + Pixel Watch)

The `mobile/` subdirectory is a Gradle multi-module Kotlin/Compose project:

- **`mobile/app/`** — phone app with Android Auto + Google TV + Chromecast support. On a TV it switches to a remote-first UI (the Stage: Now Playing as the root, an UP actions strip, DOWN browse rails) and an idle visualizer of 31 OpenGL ES 2 demo-scene effects — tunnels, plasma, fractals, fire, a sine scroller and more — rendered at 960×540 and driven by the live FFT, the waveform and the server's per-track BPM. Tuned for the Chromecast with Google TV's Mali-G31.
- **`mobile/wear/`** — Pixel Watch standalone player (browses + streams direct from server)
- **`mobile/core/`** — shared Subsonic API, models, and auth interceptor used by both

### Installing

Latest builds are attached to GitHub releases tagged **`app-vX.Y.Z`** — grab `zonik-vX.Y.Z-debug.apk` (phone) or `zonik-wear-vX.Y.Z-debug.apk` (watch). The phone app's pairing flow generates a 6-digit code that the server's `/pair` page consumes — no typing credentials on the watch. The phone can also push its `ServerConfig` to a paired watch over Bluetooth via the Wear Data Layer (**Settings → Wear OS → Send**).

### Building

```bash
cd mobile
export JAVA_HOME=$HOME/tools/jdk-17.0.12
export ANDROID_HOME=$HOME/tools/android-sdk
./gradlew assembleDebug
```

CI builds + publishes APKs automatically on every `app-v*` tag (`.github/workflows/mobile-release.yml`).

See [mobile/README.md](mobile/README.md) for the full mobile docs — features, screenshots, install flows for phone / TV / watch, and tech stack.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + Uvicorn |
| Database | SQLite (WAL) + FTS5 |
| ORM | SQLAlchemy 2.0 async |
| Task Queue | ARQ + Redis |
| Frontend | SvelteKit 5 + Tailwind CSS |
| Audio Tags | mutagen |
| Audio Analysis | Essentia |
| Vibe Embeddings | CLAP |
| AI | Claude API |
| Metadata | Last.fm + Spotify + Deezer |
| Downloads | Native Soulseek P2P client |
| Mobile (phone, TV + watch) | Kotlin · Jetpack Compose · Wear Compose Material 3 · Media3 ExoPlayer · Retrofit · Hilt |
| TV visualizer | OpenGL ES 2.0 fragment shaders · Android `Visualizer` FFT + waveform |

## License

MIT
