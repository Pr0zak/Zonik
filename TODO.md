# Zonik TODO

## Concept — Needs Design

### Multi-Library System
Enable/disable entire collections of music (e.g., Christmas, Techno/Dance/Dub, Main Library). When a library is disabled, its tracks are hidden from Symfonium and the web UI. See `plans/multi-library.md` for full implementation plan.

**Complexity: HIGH** — touches scanner, all Subsonic endpoints, new DB table, new UI page. Plan 3-4 sessions.

---

## Planned

### AI Features V2 — Enhanced AI Integration
8 new AI-powered features, each independently toggleable in Settings > AI Assistant. All use Claude API via shared client (`backend/services/ai/client.py`). See `plans/ai-features-v2.md` for full implementation plan.

**Phase 1 — High Value (implement first):**
- [x] **Shared AI Client** — extract reusable Claude API wrapper from `claude_ai.py` with rate limiting (Semaphore(2)), token tracking, response parsing. Foundation for all features.
- [x] **Natural Language Search** — "find chill tracks from last week" or "songs like Radiohead but heavier". Claude interprets intent → structured DB query. CLAP text-to-audio similarity for mood queries. Integrates into TopBar search with auto-detection. `POST /api/search/ai`
- [x] **AI Playlist Generation** — "make a playlist for a late night drive". Claude picks tracks from library using analysis data (BPM, energy, danceability) + CLAP embeddings. Creates real Playlist record. `POST /api/playlists/ai-generate`
- [x] **Enhanced "Why?" Explanations** — click any recommendation for Claude-generated deep explanation with genre connections and similar artist reasoning. `POST /api/recommendations/{id}/explain`

**Phase 2 — Smart Automation:**
- [x] **Smart Auto-Tagging** — fill empty genre/mood fields using Claude + Essentia analysis + MusicBrainz. Batch 10 tracks per call. Preview before apply. Schedulable task. `POST /api/tracks/ai-tag`
- [x] **Mood Tags** — auto-label tracks (energetic, melancholic, chill, dark, dreamy, etc.) using CLAP text-to-audio similarity (zero API cost) with optional Claude refinement. New `track_moods` table. Browseable mood filter in Library. `POST /api/tracks/ai-moods`
- [x] **Listening Insights** — weekly AI summary on Dashboard: "40% more electronic this week, taste trending toward ambient". Cached 24h. `GET /api/library/stats/insights`

**Phase 3 — Advanced Integration:**
- [x] **AI Duplicate Resolver** — Claude analyzes which duplicate to keep based on mastering quality, metadata completeness, naming conventions. Returns recommendation with reasoning per group. `POST /api/library/duplicates/ai-resolve`
- [x] **Download Quality Advisor** — AI picks best Soulseek source when results are ambiguous. Analyzes filename patterns, format, reputation. Heuristic-first (Claude only for close calls). "AI Pick" badge on results.
- [x] **AI Playlist Curator** — Claude analyzes discovered external playlists and recommends the best ones for you. Scores playlists by taste alignment (genre overlap, artist affinity, mood match), novelty (% tracks you don't own), and quality signals. Explains why each playlist fits: "Heavy on shoegaze and dream pop — matches your top genres, 60% new tracks". Works with Playlist Discovery on Discover page. `POST /api/discovery/playlists/ai-rank`
- [x] **Smart Import Advisor** — when importing an external playlist, Claude reviews the track list against your library and suggests: skip (already have better version), must-have (high taste match), and risky (low match, might not like). Per-track AI confidence badge in import preview. `POST /api/playlists/import/ai-review`

**Settings:** 10 toggles in Settings > AI Assistant (all default off/opt-in). Each flag gates UI visibility + API endpoints.

**New files:** `backend/services/ai/` package (client.py + 1 module per feature), `backend/models/mood.py`, `backend/api/ai_search.py`
**Modified:** config.py, config_api.py, settings page, TopBar, playlists page, discover page, library page, duplicates page, downloads page

---

### Playlist Import — External Playlist Search & Download
Import playlists from Spotify and Deezer by URL or search. Fetches track list, batch-matches against library, shows missing tracks, and bulk-downloads via Soulseek. Creates a local Zonik playlist with matched + downloaded tracks.

**Supported Sources:**
- **Spotify** — Public playlist URLs + search. Client credentials flow (client_id + client_secret in Settings, no user login). `GET /playlists/{id}/tracks`, `GET /search?type=playlist`
- **Apple Music** — Public playlist URLs + search. MusicKit developer token (team_id + key_id + private_key in Settings). `GET /catalog/{storefront}/playlists/{id}`, `GET /catalog/{storefront}/search?types=playlists`
- **Deezer** — Public playlist URLs + search. No auth needed. `GET /playlist/{id}/tracks`, `GET /search/playlist?q=`

**Backend:**
- `backend/services/playlist_import.py` (new) — fetch + parse external playlists
  - `fetch_spotify_playlist(url_or_id)` → `{name, tracks: [{artist, title, album, duration}]}`
  - `fetch_apple_playlist(url_or_id)` → same format
  - `fetch_deezer_playlist(url_or_id)` → same format
  - `search_spotify_playlists(query)` → `[{id, name, owner, track_count, image_url}]`
  - `search_apple_playlists(query, storefront='us')` → same format
  - `search_deezer_playlists(query)` → same format (no auth needed)
  - Spotify auth: client_credentials grant → bearer token (cached, auto-refresh)
  - Apple Music auth: JWT signed with ES256 private key (PyJWT), 6-month expiry, cached
- `POST /api/playlists/import/search` — search playlists by name on Spotify/Apple Music
- `POST /api/playlists/import/fetch` — accept URL or playlist ID, return parsed tracks with library match status (reuse batch matching pattern from discovery.py)
- `POST /api/playlists/import/create` — create local playlist from import + trigger bulk download for missing tracks
- Config: `[spotify]` section (client_id, client_secret), `[apple_music]` section (team_id, key_id, private_key_path), `[deezer]` section (no config needed, works out of the box) in zonik.toml
- Settings UI: Spotify + Apple Music credentials in Settings page (new cards); Deezer works without setup

**Frontend — New tab on Playlists page: "Import"**
- URL input + "Fetch" button (auto-detects Spotify/Apple Music/Deezer from URL)
- Search input + source toggle (Spotify/Apple Music/Deezer) for browsing playlists by name
- Search results: playlist cards with name, owner, track count, cover art
- Import preview table: artist | title | status (in library ✓ / missing ✗)
- Stats bar: total tracks, in library, missing, already downloading
- "Import & Download Missing" button → creates playlist + triggers bulk download
- Per-track download status via WebSocket (reuses Discover download pattern)

**Playlist Discovery — New tab on Discover page: "Playlists"**
Discover external playlists based on your library taste. Surfaces playlists containing tracks you already like.
- **Deezer** `GET /track/{id}/playlists` — find playlists containing your favorite/top tracks (free, no auth)
- **Spotify** `GET /search?type=playlist&q={artist}+{genre}` — search playlists by taste profile keywords
- Backend: `POST /api/discovery/playlists` — takes source (deezer/spotify), builds queries from user's top tracks + favorite artists + genre distribution
- Discovery logic:
  1. Sample ~20 tracks from favorites/top played
  2. For Deezer: fetch playlists containing each track → deduplicate → rank by overlap (playlists containing multiple of your tracks rank higher)
  3. For Spotify: build keyword queries from taste profile (top genres + artists) → search → rank by relevance
  4. Batch library match all playlist tracks → show overlap % per playlist
- Frontend: playlist cards with cover art, name, track count, overlap % badge ("12 tracks you know"), "Preview" expands track list, "Import" button → flows into Playlist Import
- Schedulable: `playlist_discovery` task discovers new playlists weekly, surfaces on Discover page
- **AI Integration** (when AI Features V2 enabled): "AI Curator" badge on playlists ranked by Claude. AI Playlist Curator scores discovered playlists by taste alignment + novelty + mood. Smart Import Advisor reviews individual tracks before download. Both optional — basic overlap ranking works without AI

**Data Flow:**
1. User pastes URL or searches → `POST /api/playlists/import/fetch`
2. Backend fetches external playlist → batch library match → returns annotated tracks
3. User reviews → clicks Import → `POST /api/playlists/import/create`
4. Backend creates Playlist with in-library tracks → bulk downloads missing via `enqueue_download()`
5. As downloads complete, tracks auto-added to playlist (via download completion hook)

**Files:** `backend/services/playlist_import.py` (new), `backend/api/playlist_import.py` (new), config.py, discover page, playlists page, settings page
**Dependencies:** PyJWT (for Apple Music token signing)

---

### Mobile UI + Swipe Actions
iOS-style swipe-to-reveal actions on all list/table rows for touch devices. Pure JS touch detection via Svelte `use:swipeRow` action + `<SwipeRow>` wrapper component. Table pages get parallel mobile card layouts. Touch-only (no desktop interference). See plan file for per-page action mappings.

**Pages:** Library, Favorites, Downloads, Discover, Upgrades, Duplicates, Logs
**Files:** `frontend/src/lib/swipe.js` (new), `frontend/src/components/ui/SwipeRow.svelte` (new), + 8 page modifications

---

## Infrastructure

All infrastructure items completed:
- [x] **SQLite → PostgreSQL Option** — `database.backend` config toggle, dialect-aware helpers in `database_compat.py`
- [x] **Background Job Dashboard** — `GET /api/jobs/dashboard` with status counts, type distribution, hourly timeline, avg duration. Job Pipeline section on Stats page with donut + timeline charts.
- [x] **API Rate Limiting** — Token bucket middleware (`backend/middleware/rate_limit.py`), configurable `rate_limit_rps` + `rate_limit_burst` in server config.

---

## Low Priority

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
