# API Reference

Examples use `http://<host>:3000` as the server address.

## Subsonic / OpenSubsonic API

Base URL: `/rest`

All endpoints support both `/endpoint` and `/endpoint.view` URL patterns. Responses are JSON by default; pass `f=xml` for XML. Endpoints marked *GET/POST* also accept form-encoded POST bodies (OpenSubsonic `formPost`).

**Authentication.** Clients may send `u` (username) + `t` (token) + `s` (salt), `u` + `p` (password, plain or `enc:`-hex), or the OpenSubsonic `apiKey` param. For token auth, `t = md5(<user's Subsonic API key> + s)` — the key is generated per user via `POST /api/users/{id}/api-key`, not the login password. Note that `/rest` handlers do **not** currently reject bad or missing credentials: `u` only selects whose stars, bookmarks, play queue and playlists are used (default `admin`). Run Zonik on a trusted network or behind an authenticating proxy.

Every `/rest` call that carries `u` is recorded (with the `c` client name) for the Live view (`/api/live/clients`).

### System

| Endpoint | Description |
|----------|-------------|
| `GET /rest/ping` | Server health check |
| `GET /rest/getLicense` | License info (always valid) |
| `GET /rest/getOpenSubsonicExtensions` | Supported extensions: `transcodeOffset`, `formPost`, `mediaType` |
| `GET /rest/getLyrics?artist=&title=` | Stub — always returns empty lyrics (Zonik stores none) |
| `GET /rest/getLyricsBySongId?id=` | Stub — always returns an empty structured-lyrics list |

### Browsing

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getMusicFolders` | Music folder list |
| `GET /rest/getIndexes` | Artist index (A-Z grouped) |
| `GET /rest/getMusicDirectory?id=` | Directory contents (artist or album) |
| `GET /rest/getArtists` | All artists with album counts |
| `GET /rest/getArtist?id=` | Artist details with albums |
| `GET /rest/getAlbum?id=` | Album details with tracks |
| `GET /rest/getSong?id=` | Single track details |
| `GET /rest/getGenres` | All genres with counts |
| `GET /rest/getArtistInfo2?id=` | Artist biography and images |
| `GET /rest/getSimilarSongs2?id=&count=` | Similar songs (vibe or fallback); `count` default 50, max 500 |
| `GET /rest/getTopSongs?artist=&count=` | Top songs by artist; `count` default 50, max 500 |

### Lists

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getAlbumList2?type=&size=&offset=` | Album lists. `type`: `alphabeticalByName` (default), `alphabeticalByArtist`, `newest`, `recent`, `frequent`, `random`, `byYear` (`fromYear`/`toYear`), `byGenre` (`genre`), `starred`. `size` max 500 |
| `GET /rest/getRandomSongs?size=&genre=&fromYear=&toYear=` | Random tracks (`size` max 500) |
| `GET /rest/getSongsByGenre?genre=&count=&offset=` | Tracks by genre |
| `GET /rest/getStarred2` | All starred items |

### Search

| Endpoint | Description |
|----------|-------------|
| `GET /rest/search3?query=` | Search artists, albums, tracks (`artistCount`/`albumCount`/`songCount` default 20, max 500, plus matching `*Offset`). Empty query = fast sync for Subsonic clients |

### Media

| Endpoint | Description |
|----------|-------------|
| `GET/HEAD /rest/stream?id=` | Stream audio. Transcodes when `format` (other than `raw`) is given, when `maxBitRate` is below the file's bitrate, or when `timeOffset` > 0 (default target mp3). Also accepts `estimateContentLength` |
| `GET/HEAD /rest/download?id=` | Download original file |
| `GET/HEAD /rest/getCoverArt?id=&size=` | Cover art image |

### Annotation

| Endpoint | Description |
|----------|-------------|
| `GET/POST /rest/star?id=&albumId=&artistId=` | Star items (params may repeat) |
| `GET/POST /rest/unstar?id=&albumId=&artistId=` | Unstar items |
| `GET/POST /rest/scrobble?id=&submission=&time=` | `submission=true` (default) records a completed play; `submission=false` is a now-playing notification. A track abandoned before half its duration counts as a skip (per `u` + `c`). `time` (ms epoch) backfills offline plays |
| `GET/POST /rest/setRating?id=&rating=` | Set rating |
| `GET /rest/getNowPlaying` | Tracks reported via `scrobble submission=false` in the last 10 minutes |

### Playlists

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getPlaylists` | All playlists |
| `GET /rest/getPlaylist?id=` | Playlist with tracks |
| `GET/POST /rest/createPlaylist?name=&songId=&playlistId=` | Create a playlist, or rename / replace the tracks of an existing one when `playlistId` is given |
| `GET/POST /rest/updatePlaylist?playlistId=&songIdToAdd=&songIndexToRemove=` | Update playlist metadata/tracks |
| `GET /rest/deletePlaylist?id=` | Delete playlist |

### Bookmarks & Play Queue

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getBookmarks` | All bookmarks |
| `GET/POST /rest/createBookmark?id=&position=&comment=` | Create bookmark |
| `GET /rest/deleteBookmark?id=` | Delete bookmark |
| `GET /rest/getPlayQueue` | Get saved play queue |
| `GET/POST /rest/savePlayQueue?id=&current=&position=` | Save play queue |

### Users

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getUser?username=` | User info |

## Zonik REST API

Base URL: `/api`

The `/api` routes have no authentication; they are meant for the bundled web UI on a trusted network. An optional per-client rate limit applies to `/api/` (config `server.rate_limit_rps` / `server.rate_limit_burst`, default 10 rps / burst 30), excluding `/api/download/` and `/api/jobs`.

Also outside `/api`: `GET /app` redirects to the newest phone/TV APK attached to an `app-v*` GitHub release.

### Library

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/library/stats` | GET | Basic library counts |
| `/api/library/stats/detailed` | GET | Detailed stats with breakdowns |
| `/api/library/stats/dashboard` | GET | Aggregated dashboard data: growth, quality, recent activity, favorites, duplicates |
| `/api/library/stats/insights` | GET | AI-generated listening insights for the week |
| `/api/library/stats/play-history?period=` | GET | Play history for charting (`24h`, `7d` default, `30d`, `90d`, `all`) |
| `/api/library/scan` | POST | Trigger library scan (returns `{job_id}`) |
| `/api/library/recent?limit=` | GET | Recently added tracks |
| `/api/library/artists?offset=&limit=&search=&sort=&order=` | GET | List artists with cover art and track counts |
| `/api/library/albums?offset=&limit=&search=&sort=&order=&artist_id=` | GET | List albums with artist and cover art |
| `/api/library/genres` | GET | Genre list with counts |

### Library Cleanup

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/library/cleanup/orphans/preview` | POST | Preview tracks whose files are missing from disk |
| `/api/library/cleanup/orphans` | POST | Remove orphaned tracks from the database |
| `/api/library/duplicates` | GET | Duplicate groups for the duplicates page |
| `/api/library/duplicates/artists` | GET | Artist IDs that have duplicate tracks |
| `/api/library/duplicates/ai-resolve` | POST | AI recommendations for which duplicates to keep |
| `/api/library/cleanup/duplicates/preview` | POST | Preview duplicate tracks |
| `/api/library/cleanup/duplicates` | POST | Remove duplicates `{remove_ids: [...], delete_files?}` |
| `/api/library/cleanup/organize/preview` | POST | Preview file rename/sort operations |
| `/api/library/cleanup/organize` | POST | Execute file rename/sort, optional `{move_ids: [...]}` |
| `/api/library/upgrades/scan` | POST | Find tracks that could be upgraded (see also `/api/upgrades/scan`) |

### Tracks

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tracks?offset=&limit=&sort=&order=&search=&genre=&artist_id=&album_id=&analyzed=&rating=` | GET | List tracks with pagination, filtering. Search uses FTS5 (title, artist, album) with ILIKE fallback. `analyzed=yes\|no`; `rating=flagged` (or `1`) |
| `/api/tracks/{id}` | GET | Track details with analysis |
| `/api/tracks/{id}` | PUT | Update track metadata `{title?, genre?, year?, track_number?}` (also writes file tags) |
| `/api/tracks/{id}` | DELETE | Delete track and file |
| `/api/tracks/{id}/play` | POST | Record a play (play count, last played, Last.fm scrobble) |
| `/api/tracks/{id}/rating?rating=` | PUT | Set 0-5 rating (0 removes it) |
| `/api/tracks/{id}/waveform?bars=` | GET | Waveform amplitude data (`bars` 10-1000, default 200; cached) |
| `/api/tracks/bulk-delete` | POST | Bulk delete `{track_ids: [...]}` |
| `/api/tracks/bulk-analyze` | POST | Queue bulk analysis `{track_ids: [...]}` |
| `/api/tracks/ai-tag` | POST | AI genre-tag suggestions `{track_ids: [...]}` |
| `/api/tracks/ai-tag/apply` | POST | Apply suggested tags `{tags: [...]}` |
| `/api/tracks/ai-moods` | POST | Tag moods via CLAP embeddings `{track_ids: [...]}` |
| `/api/tracks/moods?track_ids=` | GET | Mood tags (comma-separated IDs, or omit for all) |
| `/api/tracks/repair-tags` | POST | Parse artist/title from filenames for tracks missing metadata `{track_ids?, dry_run?=true}` |

### Search

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search/ai` | POST | Natural-language library search `{query, limit?=50}` |
| `/api/search/detect-nl` | POST | Check whether a query looks like natural language `{query}` |
| `/api/search/catalog?q=&limit=&ai=` | GET | Catalog search (Deezer, Last.fm fallback); each result carries `in_library`/`track_id`, and `job_id` when a download is already queued or running. `ai=true` also asks Claude which songs `q` describes |

### Assistant

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/assistant/voice-playlist` | POST | Turn a spoken request into an ordered list of track IDs `{prompt, size?=50, save?=false, suggest_missing?=true}`. Returns `{id, name, description, track_count, track_ids, missing}` (`id` is null unless `save`) or `{error}` |

### Downloads

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/download/search` | POST | Soulseek search `{artist?, track?, query?, timeout?=25, ai?}` (`query` may be `"Artist - Track"`). `ai=true` lets the AI download advisor rank results |
| `/api/download/trigger` | POST | Download a track `{artist, track, username?, filename?, source?, target_track_id?, exclude_users?}` |
| `/api/download/bulk` | POST | Bulk download `{tracks: [{artist, track}], source?}` (one job per track) |
| `/api/download/status` | GET | Current transfers from the native Soulseek client |
| `/api/download/cancel-transfer` | POST | Cancel active transfer `{username, filename}` |
| `/api/download/soulseek-stats` | GET | Soulseek client stats (connection, shares, peers, transfers) |
| `/api/download/soulseek-stats/history?hours=` | GET | Historical Soulseek stats for charting (default 24h) |
| `/api/download/reset-reputation` | POST | Clear all peer reputation data (cooldowns + scores) |
| `/api/download/blacklist` | GET | List blacklisted items |
| `/api/download/blacklist` | POST | Add to blacklist `{artist, track?, reason?}` |
| `/api/download/blacklist/{id}` | DELETE | Remove from blacklist |

`/api/download/internal-run` also exists but is internal (called by the worker process); don't call it directly.

**Download retry behavior**: the search tries up to four query variants (full, cleaned title, first artist) and ranks the first variant that returns results, keeping up to 5 candidates (one per peer). A download works through those candidates before marking the job failed; a direct `username`/`filename` request tries that source first, then search fallbacks. `exclude_users` skips peers, and `target_track_id` only accepts sources better than that track's current file.

### Discovery

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/discovery/top-tracks?limit=&page=` | GET | Last.fm chart with library status |
| `/api/discovery/similar-tracks?limit=` | GET | Similar to favorites |
| `/api/discovery/similar-artists?limit=` | GET | Similar artists |
| `/api/discovery/search?q=&limit=` | GET | Last.fm track search with library status |
| `/api/discovery/top-albums?artist=&limit=` | GET | Artist top albums |
| `/api/discovery/track-info?artist=&track=` | GET | Last.fm track info |
| `/api/discovery/artist-info?artist=` | GET | Last.fm artist info |
| `/api/discovery/similar-by-track?artist=&track=&limit=` | GET | Similar tracks to a specific track via Last.fm (with library status) |
| `/api/discovery/remixes?artist=&track=&limit=` | GET | Remixes, dubs and edits of one track via Last.fm |
| `/api/discovery/remix-suggestions?source=&tracks_to_scan=&limit=` | GET | Find remixes across library tracks (source: popular/favorites/random) |
| `/api/discovery/new-releases?country=` | GET | Recent album drops expanded into per-album top tracks. Sourced from Deezer, with Spotify merged in when credentials are configured. Cached 6h per country. Returns `{tracks, total, in_library, missing, fetched_at, cached}` |
| `/api/discovery/weekly-radar?mode=` | GET | `mode=tailored` reads taste-driven pending recommendations; `mode=general` mixes new releases + Last.fm chart, with in-library tracks filtered out |
| `/api/discovery/artwork/batch` | POST | Batch artwork lookup via iTunes Search `{items: [...]}` (up to 100) |
| `/api/discovery/playlists` | POST | Discover external playlists matching the library taste profile `{limit?=10}` |
| `/api/discovery/playlists/ai-rank` | POST | AI-rank discovered playlists by taste compatibility |
| `/api/discovery/lastfm/auth-url` | GET | Last.fm OAuth URL |
| `/api/discovery/lastfm/callback?token=` | GET | Exchange token for session |

**Library-match note:** every `/api/discovery/*` endpoint that flags `in_library` uses a permissive matcher: parenthetical title suffixes (`(Radio Edit)`, `(Remastered 2014)`), `feat./featuring/ft` artist sections, and comma-joined primary artists are all normalized before comparison.

### Recommendations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recommendations?limit=&offset=&status=&source=&min_score=` | GET | Paginated recommendations sorted by score |
| `/api/recommendations/refresh` | POST | Start a refresh job `{force?, limit?=100, use_claude?}` |
| `/api/recommendations/feedback` | POST | `{recommendation_id, action}` — `thumbs_up`, `thumbs_down`, `download`, `dismiss` |
| `/api/recommendations/stats` | GET | Conversion stats |
| `/api/recommendations/bulk-download` | POST | Download recommendations `{mode?=top\|above_score, count?=20, min_score?=0.7}` |
| `/api/recommendations/{id}/explain` | POST | AI explanation for a recommendation |
| `/api/recommendations/profile` | GET | Current taste profile summary |

### Favorites

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/favorites?offset=&limit=` | GET | List favorites with track/album/artist details |
| `/api/favorites/ids` | GET | Favorite IDs for quick lookup `{track_ids, album_ids, artist_ids}` |
| `/api/favorites/star` | POST | Star item `{track_id?, album_id?, artist_id?}` |
| `/api/favorites/unstar` | POST | Unstar item `{track_id?, album_id?, artist_id?}` |
| `/api/favorites/import` | POST | Bulk import `{tracks: [{title, artist, file_path?}]}` |

All favorites endpoints take an optional `user_id` query param (default `admin`).

### Playlists

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/playlists` | GET | List playlists |
| `/api/playlists` | POST | Create playlist `{name, comment?, track_ids?}` |
| `/api/playlists/generate` | POST | Smart playlist `{name, rule, value?, limit?=50}`. Rules: `genre`, `bpm_range` (value `"min-max"`), `recent`, `top_played`, `random` |
| `/api/playlists/ai-generate` | POST | Playlist from a natural-language prompt `{prompt, name?, limit?=30}` |
| `/api/playlists/{id}` | GET | Playlist details |
| `/api/playlists/{id}` | PUT | Update playlist `{name?, comment?, track_ids?}` |
| `/api/playlists/{id}` | DELETE | Delete playlist |

### Playlist Import

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/playlists/import/fetch` | POST | Fetch an external playlist by URL `{url, source?}` (auto-detects Spotify, Apple Music, Deezer) |
| `/api/playlists/import/search` | POST | Search external services for playlists `{query, sources?, limit?=10}` |
| `/api/playlists/import/import` | POST | Create a local playlist from fetched tracks `{name, tracks, download_missing?}` |
| `/api/playlists/import/ai-review` | POST | AI taste-compatibility review of fetched tracks `{tracks}` |

### Analysis

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/stats` | GET | Analysis coverage statistics |
| `/api/analysis/start?force=` | POST | Queue unanalyzed tracks for audio analysis |
| `/api/analysis/embeddings/start?force=` | POST | Queue tracks for CLAP vibe embeddings |
| `/api/analysis/enrich` | POST | Run metadata enrichment (genre, cover art) on all tracks missing data |
| `/api/analysis/echo-match` | POST | Vibe similarity search `{track_id, limit?}` |
| `/api/analysis/vibe-search` | POST | Text/track vibe search `{query?, track_id?, limit?}` |
| `/api/analysis/steady-vibes` | POST | Steady Vibes playlist from seed `{seed_track_id, length?}` |
| `/api/analysis/track/{id}` | GET | Track analysis details (BPM, key, energy, etc.) |

### Music Map

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/map/graph?max_artists=&min_genre_tracks=&include_tracks=&max_tracks_per_artist=&layout=&similarity_threshold=` | GET | Graph data for the Music Map |
| `/api/map/soundscape` | GET | Cached 2D sound projection with per-point metadata |
| `/api/map/soundscape/recompute` | POST | Recompute the projection in the background (poll `GET /soundscape`) |
| `/api/map/soundscape/locate` | POST | Place a text vibe on the map and return nearest tracks `{query, k?=12}` |
| `/api/map/listening-clock` | GET | 7x24 weekday-by-hour listening heatmap |
| `/api/map/neglected-gems?limit=` | GET | Never-played tracks ranked by closeness to your taste |
| `/api/map/gems/dismiss` | POST | Never suggest a track as a gem again `{track_id}` |
| `/api/map/audio-features` | GET | Per-track Essentia features (Camelot wheel, tempo grid) |
| `/api/map/streak-calendar` | GET | Daily play counts for a streak heatmap |
| `/api/map/sonic-path` | POST | Queue that morphs between two tracks through CLAP space `{start_id, end_id, steps?=12}` |
| `/api/map/health` | GET | Analysis-pipeline gaps that distort the map, each with a fix |

### Live

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/live/clients` | GET | Connected WebSocket clients + recently active Subsonic clients |
| `/api/live/now-playing` | GET | Tracks reported via `scrobble submission=false` |
| `/api/live/history?limit=` | GET | Recent plays with track/artist/album info |
| `/api/live/skips?sort=&limit=` | GET | Skipped tracks (inferred from scrobbles); `sort=recent` (default) or most-skipped |
| `/api/live/skips/{track_id}/reset` | POST | Forget a track's skips |
| `/api/live/skips/summary` | GET | Headline skip numbers plus most-skipped artists |

### Config

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config/services` | GET | Service connection settings (Soulseek, Lidarr, Last.fm, Spotify, Apple Music, Claude/AI feature toggles, directories) |
| `/api/config/services` | PUT | Update those settings (written to `zonik.toml`) |
| `/api/config/test/{service}` | POST | Test connectivity: `lastfm`, `soulseek`, `lidarr`, `claude` |
| `/api/config/ai-usage` | GET | Current-session AI token usage |
| `/api/config/version` | GET | Current version and git commit hash |
| `/api/config/updates` | GET | Compare local HEAD with GitHub `main` (5-min cache) |
| `/api/config/upgrade` | POST | Trigger upgrade via `upgrade.sh` (returns `{job_id}`) |
| `/api/config/restart` | POST | Restart Zonik services |
| `/api/config/health` | GET | System health check (database, Redis, Soulseek, Last.fm, Lidarr) |
| `/api/config/backup` | POST | Create database backup |
| `/api/config/backups` | GET | List available backups |
| `/api/config/restore/{filename}` | POST | Restore from backup (requires a service restart) |

### AI Usage

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai-usage/dashboard?days=&bucket=` | GET | AI usage and cost dashboard (`days` 1-365, default 30; `bucket=day\|hour`, hour only when `days` <= 2) |

### Attention

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/attention` | GET | Ranked "needs attention" items for the admin dashboard (failing jobs, failed downloads/upgrades, low-quality tracks, duplicates, Soulseek connection, disabled tasks), each with `severity` and a link. Read-only |

### Users

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/users` | GET | List users |
| `/api/users` | POST | Create user `{username, password, is_admin?}` |
| `/api/users/{id}/password` | PUT | Change password `{current_password, new_password}` |
| `/api/users/{id}/api-key` | POST | Generate a Subsonic API key (used for token / `apiKey` auth) |
| `/api/users/{id}/api-key` | DELETE | Revoke the user's API key |
| `/api/users/{id}` | DELETE | Delete user |

A default `admin` user is created on first start if no users exist.

### Device Pairing

Lets a TV or new device get server settings without typing them. Codes are 6 digits, held in memory, and expire after 5 minutes.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pair` | POST | Create a code — returns `{code, expires}` (called by the device) |
| `/api/pair/{code}` | GET | Poll: `{status: "pending"}`, `{status: "expired"}`, or `{status: "ready", url, username, api_key}` (consumed on read) |
| `/api/pair/{code}/submit` | POST | Submit `{url, username, api_key}` for a code (called from the web UI) |

### App Logs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/logs` | POST | Upload a mobile app log `{device, app_version, timestamp, logs}`. The `u` query param is stored as a hint; no auth |
| `/api/logs/app?offset=&limit=` | GET | List uploaded logs, newest first |
| `/api/logs/app/{id}` | GET | One log with full text |
| `/api/logs/app/{id}` | DELETE | Delete a log |

### Schedule

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/schedule` | GET | List scheduled tasks (includes label, description, config, last_run_at) |
| `/api/schedule/{name}` | PUT | Update task config `{enabled?, interval_hours?, run_at?, day_of_week?, count?, config?}` |
| `/api/schedule/{name}/run` | POST | Run task immediately (returns `job_id`) |

Available scheduled tasks:

| Task Name | Description |
|-----------|-------------|
| `library_scan` | Scan the music directory for new, changed, or removed files |
| `enrichment` | Fill missing genre, year and cover art from MusicBrainz, Deezer and Last.fm |
| `audio_analysis` | Run Essentia audio analysis (BPM, key, energy, danceability) on unanalyzed tracks |
| `vibe_embeddings` | Generate CLAP vibe embeddings for tracks without one, most recently played first |
| `lastfm_top_tracks` | Pull Last.fm top chart and check which tracks are in the library |
| `discover_similar` | Find tracks similar to favorites using Last.fm |
| `discover_artists` | Discover new artists related to those in your library |
| `lastfm_sync` | Push new starred tracks to Last.fm as loved tracks (incremental) |
| `playlist_weekly_top` | Auto-generate playlist of chart tracks found in library |
| `playlist_weekly_discover` | Auto-generate discovery playlist with random library mix |
| `playlist_favorites` | Rebuild Favorites playlist from all starred tracks |
| `playlist_unfavorites` | Rebuild Non-Favorites playlist from all unstarred tracks |
| `recommendation_refresh` | Build taste profile and score new track recommendations |
| `upgrade_scan` | Find low-quality tracks and search Soulseek for better copies |
| `remix_discovery` | Search for remixes of popular library tracks |
| `download_cleanup` | Remove old, empty and non-audio files from the downloads directory |
| `job_cleanup` | Prune job history (finished jobs older than 30 days, any job older than 90) |

### Upgrades

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upgrades?status=&reason=&offset=&limit=&sort=&order=` | GET | List upgrade records (filterable by status and reason) |
| `/api/upgrades/stats` | GET | Counts by status + total size delta for completed |
| `/api/upgrades/scan` | POST | Scan library for upgrade candidates `{modes?=["low_bitrate"], max_bitrate?=256, limit?=200}` |
| `/api/upgrades/start` | POST | Start downloading upgrades `{ids?: [...]}` (null = all pending) |
| `/api/upgrades/{id}/retry` | POST | Reset failed upgrade to pending |
| `/api/upgrades/{id}/skip` | POST | Mark upgrade as skipped |
| `/api/upgrades/clear?status=` | DELETE | Remove records by status (default `completed`) |

Scan modes: `low_bitrate`, `lossy_to_lossless`, `all_lossy`, `opus_to_flac`. Idempotent — skips tracks with existing pending/queued/downloading records.

### Jobs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs?offset=&limit=&type=&status=&reason=` | GET | Job history (`type` and `status` accept comma-separated lists, e.g. `download,bulk_download`; `reason` filters failed jobs by group) |
| `/api/jobs/active` | GET | Currently running jobs |
| `/api/jobs/counts?type=` | GET | Server-side counts grouped by status — `{pending, running, completed, failed, all}`. Use this for badge counts that should not depend on pagination. |
| `/api/jobs/failures?type=` | GET | Failed jobs counted per failure reason, largest first |
| `/api/jobs/retry-failed?type=&reason=` | POST | Re-queue every failed download (optionally one reason group) |
| `/api/jobs/dashboard` | GET | Job pipeline health metrics for the dashboard (24h status counts, 7d failure rate, type distribution, hourly timeline, avg duration). |
| `/api/jobs/stream/recent?limit=` | GET | Recent job updates for live display |
| `/api/jobs/{id}` | GET | Job details (result, log, tracks) |
| `/api/jobs/{id}/retry` | POST | Retry failed tracks from a failed download job |
| `/api/jobs/{id}/cancel` | POST | Cancel a pending or running job |
| `/api/jobs/clear?type=` | DELETE | Clear completed/failed history (optionally by type) |

Failure reason groups: `not_found` (no Soulseek results), `no_better` (no better-quality source), `rejected` (not imported: duplicate, not better, wrong song), `peer` (peer or transfer problem).

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `ws://<host>:3000/api/ws` | Real-time job progress + transfer updates. No auth. On connect the server sends a `job_update` for each pending/running job and a `transfer_progress` snapshot of current transfers. While idle it sends `{"type":"ping"}` every 30 seconds. Connected clients appear in `/api/live/clients`. |

WebSocket message types:

**Job updates** (`type: "job_update"`):
```json
{
  "type": "job_update",
  "job": { "id": "uuid", "type": "download", "status": "running", "progress": 3, "total": 10, "description": "..." }
}
```

**Transfer progress** (`type: "transfer_progress"`):
```json
{
  "type": "transfer_progress",
  "transfers": [
    {
      "username": "peer", "filename": "path\\file.flac", "state": "transferring",
      "total_bytes": 40000000, "received_bytes": 12000000, "progress": 30.0,
      "speed": 524288, "eta_seconds": 53, "save_path": "/downloads/file.flac", "error": null,
      "job_id": "uuid"
    }
  ]
}
```

Transfer states: `requested`, `queued`, `connected`, `transferring`, `completed`, `failed`, `denied`. `job_id` links a transfer to the job that started it.
