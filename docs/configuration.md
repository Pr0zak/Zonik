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

[database]
path = "/opt/zonik/data/zonik.db"       # SQLite database path

[redis]
url = "redis://localhost:6379/0"        # Redis URL for ARQ worker

[soulseek]
slskd_url = "http://10.0.0.116:5030"   # slskd API URL
slskd_api_key = ""                       # slskd API key
download_dir = "/music/Downloads"        # Where downloads are saved
preferred_formats = ["flac", "wav", "mp3"]  # Format preference order
min_file_size_mb = 3                     # Skip files smaller than this
max_workers = 4                          # Parallel download workers

[lidarr]
url = "http://10.0.0.179:8686"          # Lidarr API URL
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

## Getting API Keys

### Last.fm

1. Go to https://www.last.fm/api/account/create
2. Create an application
3. Copy the API Key and Shared Secret
4. For write access (scrobbling), you need the same key but with write permissions

### slskd

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
