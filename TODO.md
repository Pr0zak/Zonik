# Zonik TODO

## Concept — Needs Design

### Multi-Library System
Enable/disable entire collections of music (e.g., Christmas, Techno/Dance/Dub, Main Library). When a library is disabled, its tracks are hidden from Symfonium and the web UI. See `plans/multi-library.md` for full implementation plan.

**Complexity: HIGH** — touches scanner, all Subsonic endpoints, new DB table, new UI page. Plan 3-4 sessions.

---

## Code Review Findings

### Critical (Security & Data Integrity)

- [ ] **Add missing `ondelete="CASCADE"` to FK relationships**
  - `backend/models/favorite.py` — track_id, album_id, artist_id FKs
  - `backend/models/bookmark.py` — user_id, track_id FKs
  - `backend/models/play_queue.py` — user_id FK (CASCADE), current_track_id FK (SET NULL)
  - `backend/models/track_upgrade.py` — track_id FK
  - Generate Alembic migration after

- [ ] **Add missing database indexes**
  - `backend/models/album.py` — `index=True` on `artist_id`
  - `backend/models/bookmark.py` — `index=True` on `user_id`
  - `backend/models/playlist.py` — `index=True` on `user_id`
  - `backend/models/track_upgrade.py` — `index=True` on `status`
  - `backend/models/recommendation.py` — `index=True` on `status`
  - `backend/models/user.py` — `index=True` on `subsonic_api_key`

- [ ] **Fix detached ORM reads in download.py**
  - After `db.expunge(job)`, capture attributes into local variables before using them
  - Violates CLAUDE.md pitfall: "Never read attributes from a detached/expired ORM object after session close"

### Performance

- [ ] **Unbounded job query in download.py `_find_existing_download()`** — loads ALL jobs to find one match; add SQL WHERE + LIMIT 1
- [ ] **Bulk track deletion in tracks.py `bulk_delete_tracks()`** — 9 DELETE queries per track in loop; use IN clause
- [ ] **Rate limiter memory leak** — `backend/middleware/rate_limiter.py` `_buckets` grows unbounded; evict stale entries
- [ ] **Scanner `rglob("*")`** — scans entire tree then filters; use targeted glob for audio extensions
- [ ] **`find_duplicates()` loads ALL tracks into memory** — `backend/services/cleanup.py`; use SQL GROUP BY + HAVING

### Frontend

- [ ] **Fix polling/timer leaks on navigation**
  - `discover/+page.svelte` — `pollJob()` loops, `artworkFlushTimer`, `_pollTimer` continue after unmount
  - `discover/PlaylistDiscoveryTab.svelte` — same `pollJob()` leak
  - Cancel on `onDestroy`

- [ ] **Fix media query listener leak in +layout.svelte** — `removeEventListener` passes new function reference; store and reuse
- [ ] **Extract duplicated download/poll helpers** — `trackKey()`, `pollJob()`, `downloadTrack()` duplicated; extract to `$lib/download.js`
- [ ] **Missing AbortController cleanup** — discover page fetch calls lack signal cancellation

### Code Hygiene

- [ ] **Consolidate `FORMAT_QUALITY`** — different scales in scanner.py (1-9) vs cleanup.py (10-90)
- [ ] **Remove unused imports** — `lists.py` selectinload, `playlist_import.py` urlparse, `discovery.py` hashlib
- [ ] **Add logging to silent exception handlers** — `playlist_import.py:101`, `soulseek.py:216`, `remix_discovery.py:87`
- [ ] **Input validation on Subsonic API params** — max_bitrate, time_offset, rating range, position, size bounds
- [ ] **Hardcoded secret key** — `config.py` `secret_key = "change-me"` — log warning if unchanged

---

## Low Priority

### Pushover Notifications
Push notifications via Pushover API for key events: download complete/failed, library scan finished, upgrade found, scheduled task completion. Configurable per-event toggles in Settings.

**Backend:** `backend/services/pushover.py` (new) — send_notification(title, message, priority), event hooks in download completion, scan completion, upgrade scanner. Config: `[pushover]` section in zonik.toml (user_key, api_token, enabled events).

**Frontend:** Pushover card in Settings page with user key, API token, test button, per-event toggles.

---

### Christmas Auto-Playlist
Seasonal playlist feature — detect Christmas/holiday tracks in library and manage them as a toggleable collection. See `plans/christmas-playlist.md` for full implementation plan.

---

## Completed

### AI Music Assistant ✅
- Taste profile builder (genre histogram, top artists, favorites, audio analysis stats, CLAP centroid)
- 4-strategy candidate sourcing from Last.fm (similar tracks, similar artists, tag-based, trending)
- 7-signal weighted scoring engine (artist affinity, genre match, Last.fm similarity, audio match, CLAP similarity, popularity, novelty)
- Feedback loop: thumbs up/down adjusts future scores (1.2x/0.5x per artist)
- CLAP validation post-download (cosine similarity vs taste centroid, flags mismatches)
- Claude API integration: on-demand re-ranking with natural-language explanations + additional suggestions
- "For You" tab on Discover page with taste profile card, scored recommendations, score breakdown tooltip
- Claude API key + model selector in Settings > AI Assistant
- Scheduled task (daily 05:30) for automated recommendation refresh
- `recommendations` and `taste_profiles` database tables

### Play Stats & Listening History Charts ✅
- `play_history` table with timestamped scrobble events
- PlayHistory recorded on Subsonic scrobble + web play
- `/api/library/stats/play-history` endpoint with timeline, hourly distribution, top tracks/artists
- Chart.js charts on Stats page (plays over time, by hour of day, top tracks/artists in period)
- Time range selector: 24h, 7d, 30d, 90d

### User Ratings (Symfonium Star Ratings) ✅
- `rating` column on tracks table (nullable, 1-5)
- Subsonic `setRating` endpoint fully implemented (persists rating)
- `userRating` in Subsonic track responses
- `PUT /api/tracks/{id}/rating` REST endpoint
- StarRating component on Library list view (clickable, hover preview)
- Sortable by rating column

### Remix & Alternate Version Discovery ✅
- `backend/services/remix_discovery.py` — version type regex detection, Last.fm search
- `GET /api/discovery/remixes` endpoint with library status annotations
- "Find Remixes" context menu in Library page
- Remixes modal with version type badges, in-library status, download button

### Music Map — Library Visualization ✅
- `backend/services/graph_builder.py` — genre/artist/track graph builder
- `GET /api/map/graph` endpoint with configurable caps
- D3.js force-directed graph on `/map` route
- Genre clusters (sized by track count), artist nodes (colored by primary genre)
- Zoom levels (genre → artist), hover highlight connections, detail panel
- Drag + pin nodes, search + center, keyboard shortcut `M`
- Sidebar nav entry with teal color

### Local Timezone Display ✅
- `parseUTC()` utility in utils.js — appends `Z` to naive ISO strings from backend
- `formatDateTime()` for absolute timestamps
- `formatRelativeTime()` updated to parse as UTC
- Fixed across all pages: Dashboard, Library, Discover, Downloads, Logs, Settings, Stats, ScheduleControl

### Individual Download Queue ✅
- All download paths (single, bulk, recommendations, retry, auto-download) create individual per-track jobs
- Each track gets its own job in logs/notifications with independent status, retry, and progress tracking
- Eliminated `bulk_download` job type — all downloads use `download` type with `_do_download_inner`
- Download queue with global semaphore gates concurrency (configurable 1-10, default 4)
- Excess downloads show as "Queued" (pending) until a slot opens

### AI Recommendation Enhancements ✅
- Cover art + 30s preview URLs fetched from iTunes Search API (no key needed)
- Preview playback: hover cover art for play/pause overlay on all Discover tabs (For You, Top Tracks, Similar)
- Last.fm tag-based genre scoring replaces weak pattern matching
- Source filter pills (All/Similar/Artists/Genre/Trending/AI) with per-filter count badges
- Artwork batch fetching: backend proxy for iTunes API (CORS), debounced 50ms, 10 concurrent lookups
- Auto-download recommendations: configurable min_score + max_downloads gates in Schedule config
- CLAP vibe embeddings working on production (transformers 5.x API fixes)
- Bulk download button creates individual per-track download jobs

### AI Features V2 ✅
- Shared AI Client (`backend/services/ai/client.py`) with Semaphore(2), token tracking, persistent httpx
- Natural Language Search (`POST /api/search/ai`) with TopBar Sparkles icon integration
- AI Playlist Generation (`POST /api/playlists/ai-generate`) with prompt-based track selection
- Enhanced "Why?" Explanations (`POST /api/recommendations/{id}/explain`)
- Smart Auto-Tagging (`POST /api/tracks/ai-tag`) with preview-before-apply
- CLAP-based Mood Tags (`POST /api/tracks/ai-moods`) with 15 mood vocabulary, `track_moods` table
- Listening Insights (`GET /api/library/stats/insights`) with 24h cache, Dashboard widget
- AI Duplicate Resolver (`POST /api/library/duplicates/ai-resolve`)
- Download Quality Advisor (auto-scores Soulseek results, "AI Pick" badge)
- AI Playlist Curator + Smart Import Advisor
- 10 feature toggles in Settings > AI Assistant
- AI Usage tracking (`GET /api/config/ai-usage`)

### Playlist Import ✅
- Spotify (client credentials), Apple Music (developer token), Deezer (public API)
- URL auto-detection + search across sources
- Import preview with library match status, "Import + Download Missing" button
- Playlist Discovery tab on Discover page (taste-based search + AI ranking)
- AI Review for imported tracks (taste compatibility scoring)
- Settings: Spotify + Apple Music credential cards

### Mobile UI + Responsive ✅
- SwipeRow component + `use:swipeRow` action for touch gestures
- Responsive table columns on Upgrades page (Result, Reason, Tries)
- Responsive table columns on Logs page (Progress, Started)

### Infrastructure ✅
- Job Pipeline Dashboard on Stats page (status donut, hourly timeline, type breakdown, avg duration)
- API Rate Limiting middleware (token bucket, configurable rps/burst, per-IP)
- Optional PostgreSQL backend (dialect-aware helpers, tsvector search, connection pooling)
