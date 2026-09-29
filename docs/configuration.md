# Configuration

Zonik is configured via `zonik.toml`. The first file found is used:

1. `./zonik.toml` (working directory)
2. `/etc/zonik/zonik.toml`

If neither exists, built-in defaults apply. Every key is optional; a missing key takes the default shown below. Start from `zonik.toml.example`.

Settings are read once and cached. After editing the file by hand, restart `zonik-web` and `zonik-worker`. Saving from the web UI reloads the cached settings, but startup-time options (CORS, rate limiting, database, Redis, transcode concurrency) still need a restart.

The bind address and port that are actually used come from the uvicorn command line in `deploy/zonik-web.service` (`--host 0.0.0.0 --port 3000`), not from `[server]`.

## Full Reference

```toml
[server]
host = "0.0.0.0"          # Informational; the listen address is set in zonik-web.service
port = 3000                # Informational; the listen port is set in zonik-web.service
secret_key = "change-me"   # A warning is logged at startup while this is still "change-me"
cors_origins = []          # Allowed cross-origin origins; empty = same-origin only
rate_limit_rps = 10.0      # Per-client-IP token-bucket rate for /api/* (0 disables)
rate_limit_burst = 30      # Bucket size (maximum burst)

[library]
music_dir = "/music"                    # Root music directory
cover_cache_dir = "/opt/zonik/cache/covers"  # Extracted cover art cache
naming_scheme = "{artist}/{album}/{track_number} - {title}"  # File naming template for Rename & Sort

[database]
backend = "sqlite"                      # "sqlite" or "postgresql"
path = "/opt/zonik/data/zonik.db"       # SQLite database path
url = ""                                # PostgreSQL URL, used when backend = "postgresql"

[redis]
url = "redis://localhost:6379/0"        # Redis URL for the ARQ worker

[soulseek]
download_dir = "/downloads"              # Where downloads are saved
min_file_size_mb = 3                     # Skip search results smaller than this
username = ""                            # Soulseek username
password = ""                            # Soulseek password
listen_port = 2234                       # Inbound peer connection port
max_concurrent_downloads = 4             # Simultaneous download jobs; the rest queue (UI range 1-10)
parallel_sources = 1                     # Peers to download from at once, 1 = sequential (UI range 1-5)
source_strategy = "first"                # "first" = keep first completed, "best" = wait and keep best quality
share_library = true                     # Share the real library with peers (false = report empty shares)
server_host = "server.slsknet.org"       # Used by the Settings "Test Connection" button only
server_port = 2242                       # Used by the Settings "Test Connection" button only
slskd_url = ""                           # Legacy slskd API URL (fallback, see below)
slskd_api_key = ""                       # Legacy slskd API key
# Accepted but not read by the server: use_native, preferred_formats, max_workers

[lidarr]
enabled = false                          # Enables the Lidarr entry in Settings and the health check
url = ""                                 # Lidarr API URL (e.g. http://lidarr.example:8686)
api_key = ""                             # Lidarr API key
root_folder = "/music"                   # Lidarr root folder

[lastfm]
api_key = ""               # Last.fm read API key
write_api_key = ""         # Last.fm write API key (for scrobbling / loved-track sync)
write_api_secret = ""      # Last.fm write API secret
session_key = ""           # Filled in by the Last.fm authorisation flow
username = ""              # Filled in by the Last.fm authorisation flow

[spotify]
client_id = ""             # Spotify app credentials, used for playlist import
client_secret = ""

[apple_music]
developer_token = ""       # Apple Music developer token, used for playlist import

[analysis]
enable_essentia = true      # Enable BPM/key/energy analysis
enable_clap = true          # Enable CLAP vibe embeddings
use_gpu = false             # Run CLAP on a CUDA GPU when one is available
clap_model = "HTSAT-base"   # "HTSAT-base" = laion/clap-htsat-unfused; any other value = laion/larger_clap_music_and_speech
# Accepted but not read: max_analysis_workers (the pool uses CPU count - 1 workers)

[streaming]
max_concurrent_transcodes = 3                     # Simultaneous ffmpeg transcodes
transcode_cache_dir = "/opt/zonik/cache/transcodes"  # Cached transcoded streams
transcode_cache_max_mb = 500                       # Cache size; oldest files are evicted beyond this

[subsonic]
server_name = "Zonik"                 # Accepted but not currently read
shuffle_new_arrival_percent = 0       # % of each Shuffle Mix drawn from recently added tracks (0 = off, UI max 50)
shuffle_new_arrival_days = 30         # How recent "recently added" means (UI range 1-3650)

[assistant]
enabled = true                        # Master switch for the AI track resolver
claude_api_key = ""                   # Anthropic API key; AI features are inactive without it
claude_model = "claude-sonnet-5"      # Model for most AI features
claude_fast_model = "claude-haiku-4-5"  # Cheaper model for resolving vague song searches
track_ai_usage = true                 # Record one ai_usage row per Claude call (AI usage dashboard)
# Feature toggles
ai_reranking = true           # Claude re-ranking of recommendations
ai_search = true              # Natural-language search
ai_playlist_gen = true        # AI playlist generation
ai_explanations = true        # Recommendation explanations
ai_auto_tagging = true        # Auto-tagging
ai_mood_tags = true           # Shown in Settings; not currently read by the backend
ai_insights = true            # Library insights
ai_duplicate_resolver = true  # Duplicate resolution suggestions
ai_download_advisor = true    # Only runs when a download search asks for it (ai=true)
ai_track_resolver = true      # AI candidates for vague catalog/voice searches
ai_playlist_curator = true    # Playlist curation
# Recommendation scoring weights
w_artist_affinity = 0.25
w_genre_match = 0.20
w_lastfm_similar = 0.20
w_audio_match = 0.15
w_clap_similarity = 0.10
w_popularity = 0.05
w_novelty = 0.05

# Optional pricing overrides for the AI usage dashboard:
# model-id -> [input, output] USD per 1M tokens. Checked before the built-in
# table in backend/services/ai/pricing.py.
# [assistant.model_pricing]
# "claude-haiku-4-5" = [1.00, 5.00]
```

## Web UI Settings

Most service settings can be edited at **Settings** in the web UI (sections: Library & Storage, Soulseek, Last.fm, Lidarr, Spotify, Apple Music, Subsonic, AI Assistant). Saving writes the values back to `zonik.toml`.

Notes:

- Saving rewrites the whole file, so comments in `zonik.toml` are not preserved.
- Secret fields (passwords, API keys, tokens) are only overwritten when a new value is entered; leaving them blank keeps the existing value.
- **Test Connection** is available for Soulseek, Last.fm, Lidarr, Subsonic and Claude.
- Settings not exposed in the UI (`[server]`, `[database]`, `[redis]`, `[analysis]`, `[streaming]`, the scoring weights, `model_pricing`, `track_ai_usage`, `claude_fast_model`) are edited in the file directly.

## File Naming Scheme

The `naming_scheme` setting controls how the **Rename & Sort** cleanup tool organizes files. Available template variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `{artist}` | Artist name | `Pink Floyd` |
| `{album}` | Album title | `The Wall` |
| `{track_number}` | Zero-padded track number | `01` |
| `{title}` | Track title | `Comfortably Numb` |

**Examples:**

```toml
# Default: Artist/Album/01 - Title.flac
naming_scheme = "{artist}/{album}/{track_number} - {title}"

# Flat by artist: Artist - Title.flac
naming_scheme = "{artist} - {title}"

# Artist folders only: Artist/Title.flac
naming_scheme = "{artist}/{title}"

# No track number: Artist/Album/Title.flac
naming_scheme = "{artist}/{album}/{title}"
```

The file extension is appended automatically. The characters `<>:"/\|?*` in names are replaced with `_`. If the track has no track number, the leading ` - ` left behind is dropped.

This can also be configured from the web UI at **Settings > Library & Storage > File Naming Scheme**.

## Soulseek Download Client

### Native Client

Zonik connects directly to the Soulseek P2P network. The native client starts automatically at startup whenever `username` and `password` are set, and a keepalive loop restarts it after a sustained disconnect.

1. In **Settings > Soulseek**, enter your Soulseek username and password
2. Click **Test Connection** to verify login
3. Save

Features:
- Auto-reconnect with exponential backoff
- Peer reputation tracking in Redis (unreliable peers rank lower; nothing is blocked outright)
- Direct + indirect peer connection racing for faster downloads
- Optional multi-source downloads (`parallel_sources`, `source_strategy`)
- Real-time transfer progress via WebSocket

### Legacy slskd

The UI no longer offers slskd mode, and saving from Settings always writes `use_native = true`. The `slskd_url` / `slskd_api_key` keys are still read: when the native client is not logged in, searches fall back to the configured slskd instance.

## Getting API Keys

### Last.fm

1. Go to https://www.last.fm/api/account/create
2. Create an application
3. Copy the API Key and Shared Secret into `write_api_key` / `write_api_secret` (and the key into `api_key` for read access)
4. In **Settings > Last.fm**, start the authorisation. Last.fm redirects back to `/api/discovery/lastfm/callback`, which stores `session_key` and `username` in `zonik.toml`

### Lidarr

1. Go to Lidarr Settings > General
2. Copy the API Key

### Claude (AI Assistant)

Create an API key in the Anthropic Console and enter it at **Settings > AI Assistant**. The model can be picked there; `claude_fast_model` is file-only.

### Spotify / Apple Music

Only needed for playlist import. Spotify needs an app's client ID and secret; Apple Music needs a developer token.

## Scheduled Tasks

Configure via the web UI at `/schedule`. Tasks are stored in the database and are **disabled by default**; each has an interval, a time of day (`run_at`), an optional weekday (0 = Mon) and, for some, an item count.

| Task | Description | Default schedule |
|------|-------------|-----------------|
| library_scan | Scan music directory for new/changed/removed files | 24h at 03:00 |
| enrichment | Fill missing metadata from MusicBrainz, Deezer and Last.fm | 24h at 03:30 |
| lastfm_top_tracks | Check the Last.fm global chart against the library | 24h at 04:00, 50 |
| discover_similar | Find tracks similar to favorites | 48h at 04:30, 10 |
| discover_artists | Find artists similar to those in the library | 48h at 05:00, 10 |
| lastfm_sync | Push starred tracks to Last.fm as loved | 24h at 02:00 |
| playlist_weekly_top | Generate Weekly Top Tracks playlist | 7d, Mon 06:00, 50 |
| playlist_weekly_discover | Generate Weekly Discovery Mix | 7d, Mon 06:30, 30 |
| playlist_favorites | Rebuild Favorites playlist | 24h at 01:00 |
| playlist_unfavorites | Rebuild Non-Favorites playlist | 24h at 01:30 |
| audio_analysis | Essentia analysis (BPM, key, energy, danceability) | 24h at 02:30 |
| vibe_embeddings | CLAP vibe embeddings for tracks without one | 24h at 02:45, 300 |
| recommendation_refresh | Build taste profile and score new recommendations | 24h at 05:30 |
| upgrade_scan | Find low-quality tracks and search Soulseek for replacements | 7d, Mon 06:00, 50 |
| remix_discovery | Search for remixes and alternate versions of popular tracks | 7d, Sat 04:00, 30 |
| download_cleanup | Remove zero-byte, non-audio and >24h-old files from downloads | 24h at 01:00 |
| job_cleanup | Prune finished jobs older than 30 days, any job older than 90 | 24h at 03:00 |
