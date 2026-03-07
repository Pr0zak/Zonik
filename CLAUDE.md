# Zonik

Self-hosted music backend serving Symfonium via OpenSubsonic API.

## Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 async + SQLite (WAL+FTS5) + ARQ/Redis
- **Frontend**: SvelteKit 5 + Tailwind CSS + Chart.js + D3.js (dark theme, 14 routes)
- **Audio**: mutagen (tags), Essentia (analysis), CLAP (vibe embeddings)
- **Downloads**: Native Soulseek P2P client (or legacy slskd) with multi-strategy search + quality scoring
- **Discovery**: Last.fm API (similar tracks/artists, top charts, scrobbling)
- **Deployment**: Proxmox LXC via `create-ct.sh` interactive installer

## Commands
- Backend: `uv run uvicorn backend.main:app --reload --port 8000`
- Frontend dev: `cd frontend && npm run dev` (proxies /api and /rest to :8000)
- Worker: `uv run arq backend.workers.WorkerSettings` (requires Redis)
- Migrations: `uv run alembic upgrade head`
- New migration: `uv run alembic revision --autogenerate -m "description"`
- Verify loads: `uv run python -c "from backend.main import app; print('OK')"`
- SSH to Proxmox: `ssh root@pve5` (CT 228 on pve5)
- Upgrade production: `ssh root@pve5 "pct exec 228 -- bash -c 'cd /opt/zonik && bash upgrade.sh'"`

## Slash Commands (.claude/commands/ — local, gitignored)
- `/deploy` — push + upgrade CT 228 (with syntax/build checks)
- `/commit-deploy <msg>` — stage + commit + push + upgrade in one flow
- `/verify` — syntax check all modified Python + Svelte error check + frontend build
- `/ct-status` — services, CPU, memory, disk, running jobs, analysis coverage
- `/ct-logs [web|worker|pattern]` — check production logs (filterable by service or grep pattern)
- `/ct-jobs [running|failed|type]` — check job status on production
- `/ct-fix-jobs` — mark stuck running/pending jobs as failed after crash/upgrade
- `/ct-restart [web|worker|all]` — restart Zonik services on CT 228
- `/ct-db "SQL"` — read-only SQL query on production database
- `/ct-soulseek` — P2P client status: connection, transfers, reputation, recent downloads
- `/ct-migrate` — run Alembic migrations on production
- `/diagnose "issue"` — full investigation: services, logs, resources, API, DB

## Project Structure
```
backend/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Settings from zonik.toml (Pydantic models)
  database.py          # SQLAlchemy engine, FTS5 setup, search helpers
  models/              # 16 SQLAlchemy models (Track, Artist, Album, PlayHistory, SoulseekSnapshot, etc.)
  api/                 # REST API routes (tracks, library, download, discovery, config, etc.)
    config_api.py      # Services config + version/updates/upgrade endpoints
    jobs.py            # Job listing ({items,total} paginated), details, retry failed downloads
    tracks.py          # Track CRUD + search + bulk actions + metadata edit (writes file tags via mutagen)
    library.py         # Library stats, scan, artists/albums, cleanup (orphans/dedup/organize), upgrade scanner, duplicates management, dashboard aggregation
    download.py        # Soulseek search/trigger/bulk + enqueue_download helper + blacklist + stats + stats history + reputation reset
    discovery.py       # Last.fm charts, similar tracks/artists, remix discovery
    map.py             # Music Map graph API (genre/artist/track nodes, view modes: genre/play_heatmap/quality/duplicates)
    analysis.py        # Essentia/CLAP analysis queue + enrichment (all with WebSocket progress)
    schedule.py        # Cron scheduler management (task labels + descriptions)
    websocket.py       # Real-time job progress
    favorites.py       # Star/unstar + favorite IDs lookup + bulk import from external sources
    playlists.py       # Playlist CRUD + smart playlist generation
    users.py           # User management (CRUD, password change, API key generate/revoke)
  subsonic/            # Full OpenSubsonic API (auth, browsing, media, search, etc.)
  soulseek/            # Native Soulseek P2P client (protocol, network, transfers)
    protocol/          # Binary encode/decode, TCP framing, message types
    client.py          # Orchestrator: server + peers + transfers + search
    server_conn.py     # TCP connection to server.slsknet.org with auto-reconnect
    peer.py            # Per-user peer connections (direct + indirect)
    listener.py        # Inbound peer listener (TCP server)
    transfer.py        # Download state machine + file I/O via aiofiles
    search.py          # Multi-strategy search using native client
    reputation.py      # Peer failure tracking (in-memory + Redis), reset_all support
    shares.py          # Library file sharing — scan music dir, build compressed file list for peers
  models/
    stats.py           # SoulseekSnapshot model — periodic P2P stat snapshots for charting
  services/            # Business logic (scanner, soulseek facade, lastfm, artwork, cleanup, graph_builder (play/quality data), remix_discovery, etc.)
  workers/             # ARQ task functions + cron scheduler
  migrations/          # Alembic migrations
frontend/
  src/routes/          # SvelteKit pages (14 routes)
    +page.svelte       # Dashboard (9 widgets: stat cards, quick actions, quality gauge, growth chart, storage, transfers, activity, favorites, duplicates, tasks, P2P, health)
    library/           # Card/list views for Tracks, Artists, Albums with art + similar tracks + favorites + track edit modal + cleanup tools + upgrade scanner + remix discovery
    duplicates/        # Duplicate management — grouped cards, rich track details (format/bitrate/quality/plays), bulk remove, find upgrade
    discover/          # Last.fm charts + inline download, similar artists, For You tab (AI recs with cover art + source filters)
    downloads/         # Single-field P2P search with format filters, paginated results, WS-driven transfers, download history, blacklist
    playlists/         # Playlist management
    favorites/         # Starred items (paginated, 25/page default)
    analysis/          # Audio analysis, vibe embeddings, enrichment with real-time progress
    stats/             # Library statistics + Soulseek P2P stats (8 tiles + peer reputation grid + reset) + P2P history charts + Listening History charts (Chart.js)
    map/               # Music Map — D3.js force-directed graph with 4 view modes (genre/play heatmap/quality/duplicates)
    schedule/          # Schedule overview — groups tasks by section with links to Library/Analysis/Discover/Playlists/Settings
    logs/              # Job history with category filters + server-side pagination (25/page default) + expandable detail
    settings/          # Service config, subsonic info, updates/upgrade
  src/components/      # Sidebar (update indicator, GitHub link, active jobs, transfer mini-progress), TopBar (search + sync/bell icons), Player, Toast
    ui/                # 10 reusable components: Button, Badge, Card, Skeleton, FormInput, Modal, EmptyState, PageHeader, ScheduleControl, StarRating
  src/lib/             # api.js, stores.js, utils.js, websocket.js, schedule.js, colors.js
deploy/                # Systemd service files
docs/                  # Installation, configuration, API reference, development guide
```

## Key Design Decisions
- Track-focused (not album-focused) — download individual tracks, not discographies
- Track IDs = MD5 of relative file path (stable across scans)
- Artist/Album IDs = MD5 of normalized name key
- SQLite with FTS5 for search, populated during library scan
- All async (aiosqlite, httpx, arq)
- Subsonic auth: three methods — apiKey param (Symfonium), token+salt (md5(api_key + salt)), or password (plain/enc:hex)
- Subsonic API key: generated via POST /api/users/{id}/api-key, stored plaintext; apiKey param looks up user directly (no username needed)
- Subsonic response compat: coverArt must be entity ID (not file path), isDir/isVideo must be JSON booleans (not strings), bpm must be int (not float), artist/album must always be present (empty string, not omitted)
- search3 empty query = Symfonium fast sync
- Stream transcoding via ffmpeg (maxBitRate, format, timeOffset)
- Download blacklist system (block artists or specific tracks)
- Cover art: Deezer > Cover Art Archive > iTunes > Last.fm fallback
- Soulseek search: 4-strategy fallback (full → cleaned → track-only → first-word)
- Soulseek retry with candidate fallback: search_and_download tries up to 5 candidates before failing
- Config: zonik.toml (gitignored), zonik.toml.example (committed with empty keys)
- Service connections (slskd, Lidarr, Last.fm) configurable via web UI Settings page
- Settings page: 8 sections (Library, Soulseek, Last.fm, Lidarr, Subsonic, Users, Database, Updates), each with icon badge header and proper Button test buttons
- Download dir, cover cache dir, and file naming scheme are web-configurable
- Installer (`create-ct.sh`) only asks for infrastructure — no API keys
- SPA routing: catch-all route serves index.html for client-side SvelteKit routes
- Web UI upgrade system: check GitHub for updates, run upgrade.sh as background Job with live progress
- Sidebar shows yellow pulsing dot on Settings when update is available
- upgrade.sh supports SKIP_RESTART=1 env var (used by web UI to handle restart separately)
- Backend sends full API keys (not masked) — self-hosted single-user app, frontend password fields handle hiding
- WebSocket real-time: job progress (broadcast_job_update), transfer progress (broadcast_transfer_progress with 500ms throttle)
- "Download All Missing" fires individual /api/download/trigger per track (not bulk) for independent job tracking
- Active jobs indicator in sidebar footer (spinning loader + count, clickable → /logs)
- Sidebar transfer mini-progress: shows active transferring file with thin progress bar (blue accent, links to /downloads)
- Library scan: pre-counts files, broadcasts progress via WebSocket every 50 files, stores JSON result
- Library scan: uses db.get() for artist/album dedup (identity map aware), separate session for job completion
- SQLite single-writer constraint: never use concurrent DB sessions for writes; progress updates go through WebSocket only
- Library page: tabbed Tracks/Artists/Albums with grid (card art) and list view toggle
- Cover art served via `/rest/getCoverArt?id=<track_or_album_id>` (subsonic endpoint)
- URLSearchParams pitfall: filter out undefined/null values before passing to URLSearchParams (converts to literal "undefined")
- Svelte curly brace pitfall: literal `{text}` in HTML attributes is interpreted as JS — use `placeholder={'{artist}'}` not `placeholder="{artist}"`
- Library page: heart buttons on tracks/artists/albums in both grid and list views; 3-dot context menu on tracks (Find Similar, Edit Info, Favorite, Delete)
- Track edit: PUT /api/tracks/{id} updates DB + writes tags to audio file via mutagen (title, genre, year, track_number)
- Favorites: /api/favorites/ids returns track_ids/album_ids/artist_ids sets for fast client-side lookup
- Favorites import: /api/favorites/import accepts [{title, artist, file_path?}] and matches by file_path MD5 or title+artist
- Downloads page: sorted by status priority (queued → running → completed → failed), newest first within group
- Downloads page: single fuzzy search field sends `query` or `artist`+`track` to backend; backend SearchRequest accepts all three fields
- Downloads page: Active Transfers driven by WebSocket (no polling), paginated Download History from /api/jobs with type filter, cancel transfer + retry failed jobs
- Transfer model includes speed (bytes/sec) and eta_seconds properties; /api/jobs supports offset + type (comma-separated) params
- /api/download/cancel-transfer marks transfer FAILED, removes it, broadcasts update
- Native Soulseek client: persistent singleton in FastAPI lifespan, feature-flagged via `use_native` config toggle
- Native Soulseek: protocol layer (struct.pack/unpack), server connection with auto-reconnect (exp backoff), peer connection racing (direct vs indirect), file transfer state machine, zlib-compressed search responses
- Native Soulseek: `services/soulseek.py` is a facade — routes to native or slskd based on `use_native` flag, zero changes needed in download.py callers
- Native Soulseek: peer reputation tracking (in-memory with Redis fallback), scores adjust search result sorting (no visible cooldown badges)
- Native Soulseek: POST /api/download/reset-reputation clears all peer rep data; button on Stats page; get_summary() for per-peer scores
- Native Soulseek: multi-source parallel downloads (configurable 1-5 sources, "first" or "best" strategy), per-source error tracking in job results
- Native Soulseek: library sharing — scans music dir on startup + after scan, reports real file counts to server, responds to SharedFileListRequest from peers; configurable via share_library toggle (empty shares when disabled)
- Native Soulseek: transfer key normalization — path separators canonicalized (backslash→forward slash) to fix filename matching between search results and peer transfer offers
- Native Soulseek: server keepalive pings every 2 minutes (SET_STATUS online) to prevent idle connection drops
- Native Soulseek: search scoring includes queue_length penalty (>100: -10, >50: -6, >20: -3, >5: -1)
- Native Soulseek: sends TRANSFER_RESPONSE rejection when transfer not found (peer can retry elsewhere immediately)
- Native Soulseek: handles incoming QUEUE_UPLOAD from peers — responds with UPLOAD_DENIED (proper protocol compliance)
- Native Soulseek: handles TRANSFER_RESPONSE rejections from peers — marks transfer as DENIED
- Native Soulseek: parses QUEUE_UPLOAD (code 43) and PLACE_IN_QUEUE_REQUEST (code 51) from peers
- Native Soulseek: transient connection errors (timeout, refused, OSError) don't penalize peer reputation
- Native Soulseek file transfer protocol: PierceFirewall(relay_token) → peer sends FileTransferInit(4-byte token) → we send FileOffset(8 bytes) → peer streams file data
- Native Soulseek: relay token (from ConnectToPeer) ≠ transfer token (from TRANSFER_REQUEST) — pierce_firewall uses relay token, FileTransferInit carries transfer token
- Native Soulseek: parallel download poll_transfer uses check_cancel=False to avoid concurrent DB session access (SQLite single-writer constraint)
- Download queue: global asyncio.Semaphore in download.py gates all download paths (trigger, bulk, auto-download); max_concurrent_downloads configurable 1-10 (default 4)
- Download queue: excess downloads show as "Queued" (pending status) in bell/UI until a slot opens; semaphore resets on config save via reset_download_semaphore()
- Soulseek stats: /api/download/soulseek-stats returns connection, uptime, reconnects, peers, shares, listen port, active searches, transfers, bandwidth, speed, reputation — shown on Dashboard + Stats page
- Soulseek stats history: background collector snapshots stats every 5 minutes into soulseek_snapshots table (auto-pruned after 7 days)
- Soulseek stats charts: /api/download/soulseek-stats/history?hours=24 powers 4 Chart.js line charts (peers, transfers, speed, bandwidth) with 6h/24h/3d/7d range selector
- Scheduled audio_analysis: per-track try/except so individual track failures don't mark entire job as failed
- Essentia segfault guard: .opus files pre-converted to temp .wav via ffmpeg (MonoLoader SIGSEGV on opus); >2 channel files pre-validated with mutagen and skipped
- Essentia opus support: _NEEDS_CONVERSION set in analyzer.py, ffmpeg conversion with 30s timeout, temp file cleanup in finally block
- Analysis pool recovery: BrokenProcessPool (worker segfault) detected and pool recreated via _reset_analysis_pool(); 120s per-track async timeout
- Essentia supported formats: ESSENTIA_SUPPORTED_EXTENSIONS allowlist in analyzer.py (.mp3, .flac, .wav, .ogg, .m4a, .aac, .wma, .aiff, .alac)
- Audio analysis resilience: ProcessPoolExecutor with BrokenProcessPool recovery — if a worker crashes (segfault), pool is recreated and job continues; 120s per-track timeout prevents hangs
- Audio analysis performance: ProcessPoolExecutor (true multi-core parallelism), nice 15 priority, DB commits every 10 tracks, WS broadcasts every 10 tracks
- Analysis progress UI: shows job's own progress/total (not added to stale stats); skipped tracks shown as amber segment in progress bar with format breakdown tooltip
- Analysis stats: /api/analysis/stats returns analyzable (total minus unsupported formats), skipped count, skipped_by_format breakdown; analysis_pct based on analyzable tracks
- Enrichment: per-track 45s timeout via asyncio.wait_for, concurrent MusicBrainz + Last.fm via asyncio.gather, cover art 20s timeout
- Enrichment: proper error logging per track, cancel support (checks job status each iteration), WebSocket progress every track
- Enrichment progress: updates DB every 5 tracks (same session) so Logs page shows progress
- Track search uses FTS5 (title, artist, album) with prefix matching; falls back to ILIKE if FTS returns nothing
- Schedule controls distributed to section pages via reusable ScheduleControl component in collapsible top area (Library, Analysis, Discover, Playlists, Settings)
- Schedule page is summary/overview: groups tasks by section (incl. upgrade_scan + recommendation_refresh), shows status/interval/last run, links to respective pages
- ScheduleControl component: compact row with toggle, label, interval select, time input, optional day/count, optional auto-download button, run button
- Discover page: top tracks limit fetched from scheduled task config (default 100); per-track inline download with status (spinner/check/failed+retry)
- Discovery library matching: joins Artist table, matches exact artist + title (case-insensitive) — not loose ILIKE %title%
- Logs page: category filter tabs (All/Downloads/Library/Analysis/Discovery/Playlists), expanded job detail with colored status badges
- TopBar: global search (typeahead library + P2P), sync button (library scan), notification bell (active jobs with progress, clickable → /logs?job=id)
- Downloads page: single fuzzy search field (auto-splits "Artist - Track"), paginated P2P results (25/50/100 per page), downloads section above results
- Library page: reads `?search=` URL param on mount for TopBar navigation integration
- Favorites: total count displayed in PageHeader
- Sidebar footer: GitHub icon links to github.com/Pr0zak/Zonik
- Native Soulseek transfers: don't remove immediately on complete — let poll_transfer see final state; cleanup loop removes after 60s
- Native Soulseek transfers: state-aware cleanup — 3min for requested/queued, 2min for connected-no-data, 5min for transferring
- Native Soulseek downloads: split queue_timeout (120s, waiting for peer) vs stall_timeout (60s, no data during transfer)
- Native Soulseek downloads: auto-fallback — when direct download fails, searches for up to 4 additional peers
- Native Soulseek transfers: fuzzy filename matching in get_transfer (normalized keys + basename fallback + file size validation within 1MB tolerance)
- Pagination: library defaults to 24 per page (multiples of 12 for even grid rows: 24/48/96/192); other lists default 25/page (25/50/100/200); Jobs API returns {items, total}
- Library cleanup tools: three separate operations (orphan removal, deduplication, file organization) each with preview/dry-run before execution
- Cleanup dedup: per-track checkboxes (select/deselect all), file sizes displayed, only selected tracks removed
- Cleanup organize: per-track checkboxes (select/deselect all), only selected files moved; uses configurable naming scheme
- Naming scheme: configurable in Settings under Library, template vars {artist}/{album}/{track_number}/{title}, default "{artist}/{album}/{track_number} - {title}"
- Cleanup service in backend/services/cleanup.py: find_orphaned_tracks, find_duplicates (quality scoring + file_size), preview_organize, execute_organize, _build_target_path
- Scheduled library_cleanup task runs orphan removal only (safe default); dedup and organize are manual-only via UI
- Track upgrade scanner: POST /api/library/upgrades/scan with modes (low_bitrate, lossy_to_lossless, all_lossy), triggers bulk Soulseek download
- ScheduleControl last-run display: relative time ("2h ago") shown after label (not end of line), full timestamp on hover, guards against negative time diff
- Auto-run after scan: analysis/enrichment tasks can be auto-triggered after library scan via ScheduleTask.config JSON {auto_after_scan: true}
- Auto-download: discover tasks can auto-download missing tracks via ScheduleTask.config JSON {auto_download: true}; toggle is inline on ScheduleControl row (not separate section)
- Scheduled task runs broadcast job_update via WebSocket (bell shows running tasks); auto-download creates individual download Jobs per track
- Health check: disabled services return "warning" status which doesn't degrade overall status (only "error" degrades)
- Playlist scheduled tasks: playlist_favorites (starred tracks), playlist_unfavorites (non-starred tracks), playlist_weekly_top, playlist_weekly_discover
- Playlist detail view: click playlist to see tracks with cover art, artist, album, duration; client-side pagination
- Favorites paginated server-side: /api/favorites returns {items, total} with offset/limit
- Upgrade restarts kill background tasks (enrichment, analysis); startup lifespan marks stuck running/pending jobs as failed
- ARQ WorkerSettings.redis_settings must be a RedisSettings instance (class attribute), NOT a staticmethod — ARQ accesses .host directly
- Library tracks: analyzed filter (yes/no/all), sortable analyzed column, waveform icon per track (pink=analyzed, dim=not)
- Download completion details: filename (linked to library search), format badge, file size, source username, strategy info
- Failed download jobs include failed_sources list + source_errors array with per-source {user, error} detail
- Downloads page: failed jobs expandable to show per-source error breakdown (username + error message)
- Player bar: shows cover art (subsonic getCoverArt), track title + artist + album; progress bar uses $state + ontimeupdate for Svelte 5 reactivity
- Download import upgrade detection: import_downloaded_file checks for existing track with same normalized title+artist, compares quality (FORMAT_QUALITY rank + file size), upgrades or skips duplicates
- Download cleanup: cleanup_download_dir() runs after every download — removes zero-byte and non-audio orphan files
- Library "Added" column: sortable by created_at (defaults desc), shows formatRelativeTime() with full timestamp tooltip
- Library context menu: "Find Upgrade" navigates to /downloads?artist=X&track=Y; bulk "Find Upgrades" triggers POST /api/download/bulk
- User API keys: per-user subsonic_api_key for Symfonium token auth; generate/revoke/copy/eye-toggle in Settings > User Management
- Last.fm favorites sync: scheduled task pushes Zonik starred tracks → Last.fm loved tracks (incremental, skips already-loved)
- Last.fm auth: callback saves session_key + username to zonik.toml; session_key and username in [lastfm] config
- Settings page: 8 separate Card sections with icon badges; sticky save bar; Share Library moved to Library section; Last.fm Sync moved into Last.fm card; Subsonic styled as info-only
- Discover page: sortable column headers (click to sort asc/desc/clear, ▲/▼ indicators) on all track tables
- Discover page: iTunes artwork thumbnails on all tabs (For You, Top Tracks, Similar Tracks) via client-side cache; Music icon fallback
- Notification bell: clicking a job navigates to /logs?job=id with auto-expand
- Logs page: reads ?job= URL param to auto-expand specific job on load
- Library cleanup tools: "Danger Zone" section with amber border, DESTRUCTIVE/CAUTION tags on tool cards
- Schedule page: danger tasks (library_cleanup) shown with amber dot, AlertTriangle icon, warning badge
- Logo: text-3xl font-bold tracking-[0.15em] (bigger + wider letter spacing)
- Last.fm OAuth: auth button in Settings, auto-redirect callback with ?lastfm_auth=ok, token paste fallback
- Play history: PlayHistory model (track_id FK, played_at, source), recorded on Subsonic scrobble + web play
- Play history API: GET /api/library/stats/play-history with period param (24h/7d/30d/90d/all), returns timeline, hourly_distribution, top_tracks, top_artists
- Play history charts: Chart.js bar charts on Stats page (plays over time, by hour of day, top tracks/artists)
- User ratings: Track.rating column (nullable int 1-5), Subsonic setRating persists rating, userRating in responses
- StarRating component: 5-star rating with hover preview, click-to-rate, click-same-to-clear; sizes xs/sm/md
- Remix discovery: backend/services/remix_discovery.py — VERSION_PATTERNS regex for 14 version types, Last.fm 3-strategy search
- Remix discovery UI: "Find Remixes" context menu in Library, modal with version type badges, in-library status, download button
- Music Map: D3.js v7 force-directed graph at /map, genre clusters (sized by track count), artist nodes (colored by primary genre)
- Music Map: zoom levels (genre<0.5, artist<2.0, track>2.0), hover highlight connections, drag+pin, search+center, detail panel
- Music Map backend: graph_builder.py builds nodes/edges, GET /api/map/graph with configurable caps (max_artists, min_genre_tracks, etc.)
- Library list view: clickable artist/album cells navigate to filtered view (stopPropagation to prevent row play), removable filter pills
- Timezone: parseUTC() in utils.js appends 'Z' to naive ISO strings from backend; formatDateTime() for absolute timestamps; applied across all pages
- Per-section color coding includes map=teal (--color-map: #14b8a6), duplicates=amber (--color-duplicates: #f59e0b)
- Duplicates page: dedicated /duplicates route with enriched grouped card view — cover art, format badges (color-coded by tier), bitrate, bit_depth/sample_rate, file size, quality score bar, play count, favorite heart, added date, file path
- Duplicates API: GET /api/library/duplicates returns enriched groups with full track details + reclaimable_bytes; GET /api/library/duplicates/artists returns artist IDs with dupes (lightweight, for map overlay)
- Duplicates: find_duplicates_enriched() in cleanup.py — includes album_id for cover art, is_best flag, quality_score, play_count, rating, is_favorite, created_at
- Duplicates: confirmation modal before destructive actions (Remove from DB vs Remove + Delete Files)
- Library cleanup: dedup card replaced with link to /duplicates page (orphan cleanup and organize tools remain in Danger Zone)
- Music Map view modes: Genre (default), Play Heatmap, Quality, Duplicates — view mode selector in header bar
- Music Map Play Heatmap: recolors artist nodes by total play_count (cold blue → warm orange → hot red gradient)
- Music Map Quality: recolors by avg_quality score (green=lossless → red=low quality), low-quality nodes get "Find Upgrades" action in detail panel
- Music Map Duplicates: pulsing amber rings on artist nodes with duplicate tracks, link to Duplicates Manager in detail panel
- Music Map graph_builder: artist nodes include play_count (sum), avg_bitrate, primary_format, avg_quality (FORMAT_QUALITY + bitrate)
- Dashboard: 9 widgets — stat cards, quick actions (scan/recs/analysis/charts), quality health score (SVG circular gauge), library growth chart (30-day bar), storage by format, active transfers, recent activity feed, favorites + duplicates alert, scheduled tasks status
- Dashboard API: GET /api/library/stats/dashboard returns growth, quality_score, storage, recent_activity, favorites, duplicates, scheduled_tasks in one call
- Recommendation cover art: image_url + preview_url columns on Recommendation model, fetched from iTunes Search API (no key needed, 300x300 art + 30s preview)
- Recommendation genre scoring: Last.fm tags fetched per candidate via track.getInfo, scored as weighted overlap with user's genre_distribution (replaces weak pattern matching)
- Recommendation source filters: frontend pills (All/Similar/Artists/Genre/Trending/AI) filter by existing source field, with per-filter count badges
- Recommendation stats: GET /api/recommendations/stats — conversion funnel (total/downloaded/thumbs_up/thumbs_down/by_source/downloads_by_source)
- Recommendation bulk download: POST /api/recommendations/bulk-download with mode (top/above_score), count, min_score; creates individual download jobs per track
- All download paths (trigger, bulk, recommendations, retry, auto-download) create individual per-track download jobs — no bulk_download job type
- Download job creation: shared `enqueue_download(artist, track)` in download.py handles Job creation + semaphore queuing; used by bulk, retry (jobs.py), and recommendation bulk-download
- Sort parameter security: allowlist sets (TRACK_SORT_COLUMNS, ARTIST_SORT_COLUMNS, ALBUM_SORT_COLUMNS) prevent arbitrary attribute access via getattr()
- CORS: configurable via `cors_origins` list in [server] config (default `["*"]` for self-hosted)
- Discovery batch matching: top_tracks, similar_by_track, find_remixes use single batched query instead of per-track N+1 loops
- Cleanup request models: RemoveDupesRequest and OrganizeRequest (Pydantic) replace raw dict params in library.py
- Database indexes: Track.artist_id, Track.album_id, Favorite.track_id/album_id/artist_id, Job.type, Job.status (migration h9i0j1k2l3m4)
- Artwork batch fetching: POST /api/discovery/artwork/batch proxies iTunes Search API (CORS), 100 items max, 10 concurrent lookups; frontend debounces 50ms
- Recommendation auto-download: configurable min_score + max_downloads in ScheduleTask.config; runs after recommendation_refresh completes
- Last.fm user history: taste profile enriched with user.getTopArtists + user.getTopTracks when session_key exists (blended with local data)
- Quality upgrade scan: scheduled task (upgrade_scan, weekly Sun 06:00) finds low-quality tracks and auto-downloads upgrades from Soulseek; configurable mode (low_bitrate/lossy_to_lossless/all_lossy) + max_bitrate via UI selectors
- Schedule task backfill: list_schedule auto-adds new DEFAULT_TASKS missing from existing DB (not just on empty table)
- Section page schedule controls: collapsible "Schedule & Automation" area at top of Library, Discover, Analysis, Playlists pages (collapsed by default)
- Library page layout: pagination above schedule/danger zone sections; orphan cleanup ScheduleControl moved into Danger Zone card

## Important Files
- `zonik.toml` — Local config with real API keys (NEVER commit)
- `zonik.toml.example` — Template with empty keys (safe to commit)
- `create-ct.sh` — Proxmox host installer (creates CT + installs app, no API key prompts)
- `install.sh` — In-CT installer (for existing Debian 12 containers)
- `upgrade.sh` — Pull, rebuild, restart (also triggered from web UI Settings page)
- `pyproject.toml` — Python package definition, version string read dynamically by backend

## Frontend Notes
- Svelte 5 runes: use `$state`, `$derived` (not `{@const}` outside control blocks)
- `package.json` requires `"type": "module"` for ESM
- `@sveltejs/vite-plugin-svelte` v5+ required for vite 6
- SPA: `adapter-static` with `fallback: 'index.html'`; backend has catch-all route
- Production URL: `http://10.0.0.205:3000` (CT 228)
- Svelte 5 deprecation warnings (on:click → onclick) are harmless, builds succeed
- `stores.js` exports: sidebarOpen, currentTrack, isPlaying, activeJobs, activeTransfers, toasts, updateAvailable, addToast, showShortcuts
- `schedule.js` exports: createScheduleHelpers(getSchedTasks, setSchedTask, addToast) → {toggleSched, updateSched, runSched, toggleAutoDownload, updateSchedConfig}
- `colors.js` exports: qualityColor (Tailwind class), qualityBarColor (Tailwind class), qualityHex (hex for D3), formatBadgeClass (format tier colors), FORMAT_HEX (chart colors)
- CSS variable-based design system in `app.css` (layered backgrounds: --bg-primary/#0a0a0a → --bg-secondary → --bg-tertiary → --bg-hover)
- Per-section color coding (dashboard=indigo, library=purple, discover=green, downloads=blue, playlists=amber, favorites=red, analysis=pink, stats=cyan, map=teal, schedule=orange, logs=violet, settings=slate)
- Inter font via Google Fonts CDN; lucide-svelte icons throughout (tree-shakeable SVG icons)
- 10 reusable UI components in `frontend/src/components/ui/`: Button (6 variants), Badge (5 variants), Card, Skeleton, FormInput, Modal, EmptyState, PageHeader, ScheduleControl, StarRating
- WebSocket connected in +layout.svelte on mount
- Default admin credentials: admin/admin (created on first startup)
- Symfonium setup: generate API key in Settings > Users, use as password in Symfonium's Subsonic server config

## Infrastructure
- CT 228 on pve5 (Zonik production)
- CT 224 on pve5 (slskd — Soulseek client, `10.0.0.116:5030` — optional when native client enabled)
- CT 210 (Lidarr, `10.0.0.179:8686`)
- Mount points: `/nfs/MUSIC` → `/music`, `/nfs/DOWNLOADS` → `/downloads`

## Workflow
- Dev machine: `/home/spider/zonik` (WSL2, no sudo, no Node.js globally)
- Git remote: `https://github.com/Pr0zak/Zonik.git` (user: Pr0zak)
- Typical flow: edit → verify loads → commit → push → upgrade CT 228
- Always verify backend loads before committing: `uv run python -c "from backend.main import app; print('OK')"`
- After push, upgrade production: SSH into pve5, run upgrade.sh on CT 228

## External Services
- Soulseek P2P: Native client (direct protocol) OR legacy slskd HTTP API — toggled via `use_native` in config
- Last.fm: Read API + Write API (scrobble, love) with method signatures (set via web UI)
- Lidarr: Secondary download source (set via web UI)
- MusicBrainz: Metadata enrichment (1 req/sec rate limit)
