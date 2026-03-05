# Configuration

Zonik is configured via `zonik.toml`. The file is searched in:

1. `./zonik.toml` (working directory)
2. `/etc/zonik/zonik.toml`

## Full Reference

```toml
[server]
host = "0.0.0.0"          # Bind address
port = 3000                # HTTP port
secret_key = "change-me"   # Session secret (generate a random string)

[library]
music_dir = "/music"                    # Root music directory
cover_cache_dir = "/opt/zonik/cache/covers"  # Extracted cover art cache
naming_scheme = "{artist}/{album}/{track_number} - {title}"  # File naming template for Rename & Sort

[database]
path = "/opt/zonik/data/zonik.db"       # SQLite database path

[redis]
url = "redis://localhost:6379/0"        # Redis URL for ARQ worker

[soulseek]
slskd_url = ""                           # slskd API URL (e.g. http://host:5030) — legacy mode
slskd_api_key = ""                       # slskd API key — legacy mode
download_dir = "/downloads"              # Where downloads are saved
preferred_formats = ["flac", "wav", "mp3"]  # Format preference order
min_file_size_mb = 3                     # Skip files smaller than this
max_workers = 4                          # Parallel download workers (used for bulk downloads)
# Native Soulseek client (direct P2P, replaces slskd)
username = ""                            # Soulseek username
password = ""                            # Soulseek password
listen_port = 2234                       # Inbound peer connection port
server_host = "server.slsknet.org"       # Soulseek server host
server_port = 2242                       # Soulseek server port
use_native = false                       # Enable native client (disables slskd)

[lidarr]
url = ""                                 # Lidarr API URL (e.g. http://host:8686)
api_key = ""                             # Lidarr API key
root_folder = "/music"                   # Lidarr root folder

[lastfm]
api_key = ""               # Last.fm read API key
write_api_key = ""          # Last.fm write API key (for scrobbling)
write_api_secret = ""       # Last.fm write API secret

[analysis]
enable_essentia = true      # Enable BPM/key/energy analysis
enable_clap = true          # Enable CLAP vibe embeddings
use_gpu = false             # Use Intel iGPU for CLAP (requires OpenVINO)
clap_model = "HTSAT-base"  # CLAP model variant
max_analysis_workers = 2    # Parallel analysis workers

[subsonic]
server_name = "Zonik"       # Server name reported to clients
```

## Service Connections

Service connections (Soulseek, Lidarr, Last.fm) can be configured from the web UI at **Settings > Service Connections**. Changes are saved directly to `zonik.toml`.

You can also edit `zonik.toml` directly if you prefer.

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

The file extension is appended automatically. Special characters in names are sanitized. If `{track_number}` is missing from the track metadata, it is omitted gracefully.

This can also be configured from the web UI at **Settings > Library > File Naming Scheme**.

## Soulseek Download Client

Zonik supports two modes for Soulseek downloads:

### Native Client (Recommended)

Direct connection to the Soulseek P2P network — no external dependencies:

1. In Settings, check **"Native Client"**
2. Enter your Soulseek username and password
3. Click **Test** to verify login
4. Save

The native client connects directly to `server.slsknet.org`, manages peer connections, and handles file transfers natively. Features:
- Auto-reconnect with exponential backoff
- Peer reputation tracking (blocks unreliable peers for 24h)
- Direct + indirect peer connection racing for faster downloads
- Real-time transfer progress via WebSocket

### Legacy slskd (Deprecated)

Uses a separate slskd container as a Soulseek proxy:

1. Deploy an slskd instance (e.g. CT 224)
2. In Settings, uncheck "Native Client"
3. Enter the slskd URL and API key
4. Click Test to verify

### Switching Between Modes

The `use_native` toggle in Settings controls which backend is used. The switch takes effect after saving — running downloads will continue on the current backend.

## Getting API Keys

### Last.fm

1. Go to https://www.last.fm/api/account/create
2. Create an application
3. Copy the API Key and Shared Secret
4. For write access (scrobbling), you need the same key but with write permissions

### slskd (Legacy)

1. Your slskd instance should have an API key configured
2. Find it in slskd's `options.yaml` under `web > authentication > api_keys`

### Lidarr

1. Go to Lidarr Settings > General
2. Copy the API Key

## Scheduled Tasks

Configure via the web UI at `/schedule`. Available tasks:

| Task | Description | Default Interval |
|------|-------------|-----------------|
| library_scan | Scan music directory for new/changed files | 24h |
| enrichment | MusicBrainz + Last.fm metadata enrichment | 24h |
| lastfm_top_tracks | Check Last.fm chart for missing tracks | 24h |
| discover_similar | Find similar tracks from favorites | 48h |
| lastfm_sync | Sync loved tracks with Last.fm | 12h |
| playlist_weekly_top | Generate Weekly Top Tracks playlist | 168h (7d) |
| playlist_weekly_discover | Generate Weekly Discover playlist | 168h (7d) |
| playlist_favorites | Update Favorites playlist | 12h |
| audio_analysis | Analyze unprocessed tracks | 24h |
| cover_art_fetch | Fetch missing cover art | 24h |
| library_cleanup | Remove orphaned records | 168h (7d) |
