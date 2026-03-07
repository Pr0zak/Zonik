# Zonik TODO

## Concept — Needs Design

### Multi-Library System
Enable/disable entire collections of music (e.g., Christmas, Techno/Dance/Dub, Main Library). When a library is disabled, its tracks are hidden from Symfonium and the web UI. See `plans/multi-library.md` for full implementation plan.

**Complexity: HIGH** — touches scanner, all Subsonic endpoints, new DB table, new UI page. Plan 3-4 sessions.

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
