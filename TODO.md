# Zonik TODO

## Concept — Needs Design

### AI Music Assistant
An intelligent recommendation engine that suggests tracks to download based on your listening patterns, library composition, and taste profile. See `plans/ai-music-assistant.md` for full implementation plan.

**Complexity: HIGH** — new service, new API, new UI, taste profiling, multiple data sources. Plan 2-3 sessions.

**Depends on:** Play Stats (for play history signals), Audio Analysis (for CLAP embeddings)

---

### Multi-Library System
Enable/disable entire collections of music (e.g., Christmas, Techno/Dance/Dub, Main Library). When a library is disabled, its tracks are hidden from Symfonium and the web UI. See `plans/multi-library.md` for full implementation plan.

**Complexity: HIGH** — touches scanner, all Subsonic endpoints, new DB table, new UI page. Plan 3-4 sessions.

---

## Low Priority

### Christmas Auto-Playlist
Seasonal playlist feature — detect Christmas/holiday tracks in library and manage them as a toggleable collection. See `plans/christmas-playlist.md` for full implementation plan.

---

## Completed

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
- "Download All Missing" on Discover + Library similar tracks now fires individual `/api/download/trigger` per track
- Each track gets its own job in the logs with independent status tracking
- Replaced bulk job approach (`/api/download/bulk`) for similar/missing track downloads
