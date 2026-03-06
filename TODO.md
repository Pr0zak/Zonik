# Zonik TODO

## Concept — Needs Design

### AI Music Assistant
An intelligent recommendation engine that suggests tracks to download based on your listening patterns, library composition, and taste profile.

**Problem:**
- Current discovery is manual: check Last.fm charts, browse similar tracks, search by name
- No personalized recommendations — Last.fm similar tracks are generic, not tailored to YOUR library
- User has to actively seek out new music instead of being presented with smart suggestions

**Concept:**
A "Suggestions" feed that learns from your library and behavior, then recommends tracks you'd likely enjoy but don't have yet. Think Spotify Discover Weekly but for a self-hosted library.

**Data signals available in Zonik:**
1. **Library composition**: genres, artists, albums you already own
2. **Favorites**: starred tracks = strong positive signal
3. **Play counts**: most played = preferred tracks/artists
4. **Play history**: (once implemented) listening patterns, time-of-day preferences
5. **Audio analysis**: BPM, key, energy, danceability from Essentia
6. **CLAP embeddings**: vibe/mood vectors — semantic similarity between tracks
7. **Download history**: what you've searched for and downloaded
8. **Skipped downloads**: blacklisted artists/tracks = negative signal

**Architecture options:**

#### Option A: Rule-Based Recommendations (No AI, Quick to Build)

Weighted scoring from multiple signals, no ML needed.

```
Score = (genre_match × 3) + (artist_similarity × 2) + (bpm_proximity × 1) + (energy_match × 1) + (popularity × 0.5)
```

**Sources for candidates:**
1. Last.fm similar artists → their top tracks (already have this API)
2. Last.fm similar tracks from favorites (already have this)
3. Last.fm tag-based discovery (e.g., your top genres → tracks tagged with those genres)
4. Soulseek browse: popular tracks from peers who share similar music

**Scoring each candidate:**
- Genre overlap with library: +3 per matching genre
- Artist already in library (different track): +2
- Similar BPM range to favorites: +1
- Similar energy/danceability to favorites: +1
- Last.fm match score: +0-2
- Already downloaded/blacklisted: -∞

**Pros:** Simple, explainable, no dependencies, fast
**Cons:** Basic pattern matching, not truly "intelligent"

#### Option B: Embedding-Based Similarity (Uses Existing CLAP)

Use the CLAP vibe embeddings already computed for analyzed tracks to find similar-sounding music.

**How it works:**
1. Compute average embedding vector from favorites (= "taste profile")
2. When discovering new tracks, analyze a preview/sample
3. Compare candidate embedding to taste profile via cosine similarity
4. Rank by similarity score

**Problem:** We can't get audio embeddings for tracks we don't have yet. CLAP needs the audio file.

**Workaround — Two-phase approach:**
1. Phase 1: Use Last.fm/metadata signals to generate candidates (Option A)
2. Phase 2: After downloading, compute CLAP embedding and compare to taste profile
3. If embedding similarity is low → flag as "might not match your taste" (auto-unfavorite suggestion)

**Pros:** Leverages existing Essentia/CLAP analysis
**Cons:** Can only evaluate AFTER download, not before

#### Option C: Claude API Integration (True AI Recommendations)

Use Claude to analyze your library profile and generate natural-language music recommendations.

**How it works:**
1. Build a taste profile summary: top genres, favorite artists, BPM range, energy profile, mood words
2. Send to Claude API: "Given this music taste profile, suggest 20 tracks I should look for"
3. Claude returns artist/track suggestions with reasoning
4. Cross-reference with Last.fm to verify tracks exist
5. Search Soulseek for availability
6. Present suggestions with Claude's reasoning ("Because you like X, you might enjoy Y")

**Example prompt:**
```
Music taste profile:
- Top genres: Techno (35%), House (20%), Ambient (15%), IDM (10%)
- Favorite artists: Aphex Twin, Boards of Canada, Burial, Four Tet
- Avg BPM: 125, Energy: 0.7, Danceability: 0.8
- Recent favorites: dark, atmospheric electronic with complex rhythms

Suggest 20 tracks not by these artists that match this taste.
Return as JSON: [{artist, track, reason}]
```

**Pros:** Most intelligent, explains reasoning, handles nuance, discovers non-obvious connections
**Cons:** API costs, rate limits, latency, requires Anthropic API key config

#### Option D: Hybrid (Recommended)

Combine Options A + C:
1. **Daily/weekly**: Rule-based scoring generates candidate list (fast, free, runs as scheduled task)
2. **On-demand**: "Ask AI" button sends taste profile to Claude for curated suggestions
3. **Post-download**: CLAP embedding check validates if downloaded track matches taste

**Frontend — Suggestions Page or Discover Tab:**
- "For You" feed: ranked list of suggested tracks with download buttons
- Each suggestion shows: track, artist, reason ("Similar to your favorite Burial tracks"), source signal
- Filters: genre, mood, energy level
- "Refresh Suggestions" button (re-runs scoring)
- "Ask AI" button (sends to Claude, shows natural-language recommendations)
- Thumbs up/down on suggestions → improves future scoring

**Backend components:**
- `backend/services/recommendations.py` — scoring engine
- `backend/api/recommendations.py` — API endpoints
- Taste profile builder: aggregates library stats into a profile object
- Candidate sourcing: Last.fm similar + tag discovery
- Scoring + ranking pipeline
- Optional: Claude API integration for AI suggestions

**Config:**
```toml
[recommendations]
enabled = true
refresh_interval_hours = 24
max_suggestions = 50
claude_api_key = ""  # optional, for AI suggestions
```

**Implementation order:**
1. Taste profile builder (aggregate genres, artists, BPM, energy from library)
2. Candidate sourcing (Last.fm similar artists → top tracks, tag-based discovery)
3. Scoring engine (weighted multi-signal scoring)
4. API endpoint: `GET /api/recommendations` with `refresh` param
5. Frontend: Suggestions tab on Discover page (or new page)
6. Scheduled task: `generate_recommendations` (daily)
7. Optional: Claude API integration for "Ask AI" feature
8. Optional: Feedback loop (thumbs up/down adjusts weights)

**Complexity: HIGH** — new service, new API, new UI, taste profiling, multiple data sources. Plan 2-3 sessions for base (Option A), +1 for Claude integration.

**Depends on:** Play Stats (for play history signals), Audio Analysis (for CLAP embeddings)

---

### Music Map — Library Visualization
An interactive visual graph showing connections between artists, genres, and tracks in your library. Explore your music collection as a network of relationships.

**Problem:**
- Library is currently a flat list — no way to see how music connects
- Hard to grasp the shape of your collection: which genres dominate, which artists cluster together, where the gaps are
- Discovering relationships between artists requires manual browsing

**Concept:**
A force-directed graph (network diagram) where nodes are artists/genres/tracks and edges represent relationships. Zoom in to see individual tracks, zoom out to see genre clusters. Interactive — click a node to play, see details, find similar.

**Visualization layers (zoom levels):**

1. **Genre Map** (zoomed out) — large colored bubbles per genre, size = track count, proximity = how often genres co-occur in library
2. **Artist Network** (mid zoom) — artist nodes connected by similarity (Last.fm similar artists), colored by primary genre, sized by track count
3. **Track Constellation** (zoomed in) — individual tracks around their artist node, connected to similar tracks (via CLAP embedding cosine similarity)

**Data sources for connections:**
- **Genre co-occurrence**: artists/tracks sharing genres → cluster together
- **Last.fm similar artists**: edges between artists Last.fm considers similar (already have this API)
- **CLAP embeddings**: cosine similarity between track embeddings → edges between similar-sounding tracks
- **Favorites**: starred nodes glow / highlighted border
- **Play count**: node size or brightness scales with plays
- **Shared albums**: tracks on same album → tightly clustered

**Technology options:**

#### Option A: D3.js Force-Directed Graph
The classic approach for network visualizations.

**Pros:**
- Mature, well-documented, huge ecosystem
- Full control over layout, styling, interactions
- SVG-based — crisp at any zoom level
- Can handle 500-1000 nodes with good performance

**Cons:**
- Complex API, steep learning curve
- Performance degrades above ~2000 nodes (need WebGL for large libraries)
- Heavy bundle size (~250KB)

#### Option B: vis-network (vis.js)
Simpler force-directed graph library, purpose-built for network diagrams.

**Pros:**
- Much simpler API than D3
- Built-in clustering, zoom, pan, node selection
- Canvas-based — better performance for large graphs
- Good for 1000-5000 nodes

**Cons:**
- Less visual control than D3
- Dated look without heavy customization
- Smaller community

#### Option C: Sigma.js + Graphology
Modern WebGL-based graph renderer. Best for large datasets.

**Pros:**
- WebGL — handles 10,000+ nodes smoothly
- Graphology library for graph algorithms (community detection, centrality)
- Modern, active development
- Good zoom/pan performance

**Cons:**
- WebGL setup more complex
- Less SVG-like styling control
- Newer, smaller ecosystem

#### Recommendation: D3.js (Option A) for MVP
Start with D3 force-directed graph — it's the most flexible, well-supported, and fits the existing frontend stack. If performance becomes an issue with large libraries (5000+ tracks), migrate to Sigma.js.

**Backend API:**
```
GET /api/stats/music-map
  ?layer=genres|artists|tracks
  &limit=200           # max nodes
  &min_connections=1   # filter isolated nodes
  &center_artist=      # optional: focus on one artist's neighborhood
```

**Response structure:**
```json
{
  "nodes": [
    {"id": "artist_123", "label": "Aphex Twin", "type": "artist", "genre": "IDM", "size": 45, "favorite": true},
    {"id": "genre_techno", "label": "Techno", "type": "genre", "size": 120}
  ],
  "edges": [
    {"source": "artist_123", "target": "artist_456", "weight": 0.85, "type": "similar"},
    {"source": "artist_123", "target": "genre_idm", "type": "genre_member"}
  ],
  "clusters": [
    {"id": "cluster_0", "label": "Electronic", "genres": ["Techno", "House", "IDM"], "color": "#4f46e5"}
  ]
}
```

**Frontend — New route: `/map`**
- Full-screen graph visualization (no sidebar, minimal chrome)
- Toolbar: layer selector (Genres / Artists / Tracks), zoom controls, search, filter by genre
- Click node → side panel with details (artist info, play count, top tracks, similar)
- Double-click artist → zoom into their track constellation
- Right-click → Play, Find Similar, Download Similar
- Color coding: nodes colored by genre (same section colors from app)
- Animated: nodes gently float, new connections animate in
- Favorites highlighted: gold border or glow effect

**Interactive features:**
- **Search**: highlight a node and its connections, dim everything else
- **Filter**: show only certain genres, only favorites, only recently played
- **Path finding**: "How does Artist A connect to Artist B?" — highlight shortest path
- **Cluster detection**: auto-group related artists, label clusters
- **Time dimension** (future): animate how library grew over time (needs play_history)

**Backend components:**
- `backend/api/music_map.py` — graph data API
- Graph builder: query artists, genres, tracks, compute edges from Last.fm similarity + CLAP embeddings
- Caching: graph computation is expensive — cache result, invalidate on library scan
- Edge weight calculation: combine Last.fm match score + CLAP cosine similarity + genre overlap

**Implementation order:**
1. Backend: graph data builder (artists + genre edges from DB)
2. Backend: API endpoint with caching
3. Frontend: basic D3 force graph with artist nodes + genre clusters
4. Frontend: click interactions (details panel, play, navigate)
5. Backend: add CLAP embedding similarity edges (requires analyzed tracks)
6. Frontend: track-level zoom with CLAP-based connections
7. Frontend: search, filter, path-finding features
8. Polish: animations, responsive, performance tuning

**Complexity: HIGH** — new D3.js dependency, graph algorithm computation, full-screen interactive UI, multiple zoom levels. Plan 3-4 sessions.

**Depends on:** Audio Analysis (for CLAP embedding edges), Last.fm (for artist similarity edges). Basic genre/artist map works without either.

---

## Medium Priority

### Play Stats & Listening History Charts
Track when and what is played via Symfonium scrobbles and show listening charts on the Stats page.

**Current state:**
- Symfonium sends `scrobble` to Subsonic API on each play → Zonik increments `track.play_count` + `track.last_played_at`
- Stats page already shows "Most Played" list from play_count
- BUT: no history — we only store the running total, not individual play events
- Can't chart "plays per day" or "listening hours this week" without timestamped events

**What we need:**
- A `play_history` table to log each scrobble with timestamp
- API endpoints to aggregate play data for charting
- Chart.js charts on the Stats page (same pattern as Soulseek stats charts)

**Schema:**
```sql
CREATE TABLE play_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    played_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'subsonic'  -- 'subsonic', 'web', 'api'
);
CREATE INDEX idx_play_history_played_at ON play_history(played_at);
CREATE INDEX idx_play_history_track_id ON play_history(track_id);
```

**Backend changes:**
- Alembic migration for `play_history` table
- Update `subsonic/annotation.py` scrobble: INSERT into play_history (in addition to incrementing play_count)
- Update `api/tracks.py` POST `/{id}/play`: also INSERT into play_history
- New API endpoint: `GET /api/stats/listening`
  - Params: `hours=168` (default 7 days), `group_by=hour|day|week`
  - Returns: `{ plays: [{time, count}], top_tracks: [{title, artist, plays}], top_artists: [{name, plays}], total_plays, total_hours }`
- Auto-prune: keep 90 days of history (scheduled cleanup or on-write)

**Frontend — Stats page charts:**
1. **Plays Over Time** (line chart) — plays per day/hour, 7d/30d/90d range selector
2. **Listening Hours** (bar chart) — hours listened per day
3. **Top Tracks This Week/Month** (horizontal bar chart) — most played tracks in period
4. **Top Artists This Week/Month** (horizontal bar chart) — most played artists in period
5. **Listening Heatmap** (optional, low priority) — hour-of-day × day-of-week grid

**Chart layout on Stats page:**
- New "Listening" section above or below existing Soulseek stats
- Same time range selector pattern (6h/24h/3d/7d/30d)
- Same Chart.js line/bar chart styling

**Data flow:**
```
Symfonium plays track
  → POST /rest/scrobble?id=xxx
  → subsonic/annotation.py: track.play_count++, INSERT play_history
  → Stats page: GET /api/stats/listening?hours=168
  → Chart.js renders plays over time
```

**Implementation order:**
1. Alembic migration: create `play_history` table
2. Update scrobble endpoint: log to play_history
3. Update web play endpoint: log to play_history
4. Add `/api/stats/listening` endpoint with aggregation queries
5. Add Chart.js charts to Stats page
6. Add auto-prune (90-day retention)

**Complexity: MEDIUM** — new table + migration, 2 endpoint updates, 1 new API, frontend charts. ~1 session.

---

### Remix & Alternate Version Discovery
Search for remixes, dubs, edits, and other alternate versions of tracks already in the library, and download them to expand the collection.

**Concept:**
- For each track in library (or favorites), search Last.fm and Soulseek for alternate versions
- Match patterns: "Track Name (Remix)", "Track Name (Dub Mix)", "Track Name (Extended)", "Track Name (Radio Edit)", "Track Name (Instrumental)", "Track Name (Acoustic)", "Track Name (Live)", etc.
- Avoid re-downloading the vanilla version or versions already in library

**Backend:**
- New discovery endpoint: `GET /api/discovery/remixes?track_id=<id>&limit=20`
  - Takes a library track, searches Last.fm + Soulseek for alternate versions
  - Returns list with `{artist, name, version_type, in_library}` annotations
- New scheduled task `discover_remixes` — batch process favorites or entire library
  - Configurable: favorites only vs full library
  - Stores missing remixes in job.tracks for download
- Search strategy:
  1. Last.fm `track.search` with "Artist - Track remix" / "Artist - Track dub" queries
  2. Soulseek search with title + version keywords (remix, dub, extended, etc.)
  3. Deduplicate results by normalized artist+title
- Version type detection via regex on title suffixes:
  - `(.*Remix.*)`, `(.*Dub.*)`, `(.*Mix.*)`, `(.*Extended.*)`, `(.*Edit.*)`, `(.*Instrumental.*)`, `(.*Acoustic.*)`, `(.*Live.*)`, `(.*VIP.*)`, `(.*Bootleg.*)`

**Frontend:**
- Discover page: new "Remixes" tab or sub-section for batch discovery
- Per-track "Find Remixes" in library context menu (3-dot menu) — like "Find Similar"
- Per-track "Find Remixes" on Discover similar-by-track page (`/discover?artist=X&track=Y&mode=remixes`)
- Results table: Track, Artist, Version Type, Status (in library / download)
- Bulk download missing remixes
- Inline per-track download with status (same pattern as top tracks / similar tracks)

**Auto-download option:**
- ScheduleTask.config `{auto_download: true}` like existing discover tasks

**Implementation order:**
1. Add version detection regex utility in `backend/services/discovery.py`
2. Add `/api/discovery/remixes` endpoint
3. Add `discover_remixes` scheduled task
4. Add "Find Remixes" to library context menu
5. Add Remixes tab/section to Discover page
6. Add ScheduleControl + auto-download toggle

---

## Concept — Needs Design

### Multi-Library System
Enable/disable entire collections of music (e.g., Christmas, Techno/Dance/Dub, Main Library). When a library is disabled, its tracks are hidden from Symfonium and the web UI — they still exist on disk but are invisible.

**Use cases:**
- Hide Christmas music outside December
- Separate Techno/Dance/Dub collection that can be toggled for parties
- Keep a "Main" library always on, toggle specialty collections on/off
- Different moods/vibes as switchable libraries

#### Option A: Subsonic Music Folders (Recommended)

Subsonic API has built-in `getMusicFolders` — clients like Symfonium already support filtering by folder. This is the most natural fit.

**How it works:**
- Each "library" maps to a Subsonic music folder (physical directory or virtual)
- `getMusicFolders` returns the list of libraries with enabled/disabled state
- Symfonium's `musicFolderId` param filters all browsing/search to that folder
- Zonik filters responses server-side when a library is disabled

**Schema:**
```sql
CREATE TABLE music_libraries (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- "Main", "Christmas", "Techno/Dance"
    enabled BOOLEAN DEFAULT TRUE, -- visible to clients when true
    detection_rules TEXT,         -- JSON: keyword/genre matching rules (nullable)
    sort_order INTEGER DEFAULT 0,
    created_at DATETIME
);

-- Track belongs to one library (simple) or many (flexible)
ALTER TABLE tracks ADD COLUMN library_id INTEGER REFERENCES music_libraries(id) DEFAULT 1;
```

**Assignment methods:**
1. **Directory-based**: tracks in `/music/Christmas/` auto-assign to "Christmas" library
2. **Rule-based**: genre contains "Techno" or "House" → auto-assign to "Techno/Dance" library
3. **Manual**: drag tracks between libraries in web UI
4. **Hybrid**: auto-detect on scan + manual override

**Pros:**
- Native Subsonic support — Symfonium already handles `musicFolderId`
- Simple: one `library_id` column on tracks table
- Toggle = just flip `enabled` flag, instant effect
- Subsonic clients can filter per-folder natively

**Cons:**
- Track can only belong to one library (unless many-to-many)
- Physical dirs add complexity to file organization
- Need to filter ALL Subsonic endpoints (search, browse, stream)

#### Option B: Tag/Collection System (Gmail-like Labels)

Tracks can belong to multiple collections via a join table. More flexible but more complex.

**Schema:**
```sql
CREATE TABLE collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    color TEXT,                    -- UI accent color
    icon TEXT,                     -- lucide icon name
    detection_rules TEXT,          -- JSON auto-detection rules
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE track_collections (
    track_id TEXT REFERENCES tracks(id),
    collection_id TEXT REFERENCES collections(id),
    PRIMARY KEY (track_id, collection_id)
);
```

**Pros:**
- Track in multiple collections (Christmas + Chill + Main)
- No file moving needed
- Very flexible tag-like system

**Cons:**
- More complex queries (JOIN on every request)
- Subsonic `musicFolderId` expects exclusive folders, not overlapping labels
- Every Subsonic endpoint needs collection-aware filtering
- Performance impact on large libraries (extra JOIN)

#### Option C: Virtual Directories (Filesystem-based)

Each library is a physical subdirectory. Scanner assigns `library_id` based on path prefix.

**Config:**
```toml
[[libraries]]
name = "Main"
path = "/music"
enabled = true

[[libraries]]
name = "Christmas"
path = "/music/Christmas"
enabled = false

[[libraries]]
name = "Techno/Dance"
path = "/music/Techno"
enabled = true
```

**Pros:**
- Simplest to implement — library = directory prefix match
- Maps directly to Subsonic music folders
- No extra DB tables needed (derive from file_path)
- Easy to understand: put files in a folder = assign to library

**Cons:**
- Moving a track between libraries means moving the file
- Tracks can only be in one library (directory-based)
- Nested directories create ambiguity (`/music/Christmas/Techno/` = which library?)

#### Recommendation: Option A (Music Folders) + Rule-Based Detection

Combine Subsonic music folders with smart auto-detection:

1. **music_libraries table** with name, enabled, detection_rules
2. **library_id on tracks** (FK, default = "Main")
3. **Auto-detection on scan**: match genre/title/album against rules, assign library_id
4. **Manual override**: reassign tracks via web UI
5. **Subsonic filtering**: all endpoints check library.enabled, respect musicFolderId param
6. **Web UI**: Libraries page or section in Settings with toggle switches per library

**Detection rules format:**
```json
{
  "genres": ["Techno", "House", "Trance", "Drum and Bass", "Dubstep"],
  "title_keywords": [],
  "album_keywords": [],
  "directory_prefix": "/music/Techno"
}
```

**What needs filtering (Subsonic endpoints):**
- `getIndexes`, `getMusicDirectory`, `getAlbumList`, `getAlbumList2`
- `search2`, `search3`
- `getRandomSongs`, `getSongsByGenre`
- `getStarred`, `getStarred2`
- `getPlaylists` (exclude playlists with only disabled-library tracks)

**What does NOT need filtering:**
- `stream`, `download`, `getCoverArt` (direct ID access — if you have the ID, you can play it)
- `scrobble`, `star`, `unstar`

**Implementation order:**
1. Design: finalize schema, decide on assignment strategy
2. Migration: add `music_libraries` table + `library_id` column on tracks
3. Scanner: assign library_id during scan (rule-based + directory prefix)
4. Subsonic: update `getMusicFolders` to return real libraries
5. Subsonic: add `library_id` filtering to all browsing/search endpoints
6. API: CRUD endpoints for libraries (`/api/libraries`)
7. Frontend: Libraries management UI (create, edit rules, toggle on/off)
8. Frontend: Library selector in sidebar or top bar
9. Test with Symfonium: verify musicFolderId filtering works end-to-end

**Complexity: HIGH** — touches scanner, all Subsonic endpoints, new DB table, new UI page. Plan 3-4 sessions.

**Depends on:** Nothing, but Christmas Auto-Playlist becomes a special case of this (Christmas = a library with detection rules for holiday keywords).

---

### User Ratings (Symfonium Star Ratings)
Persist per-track 1-5 star ratings from Symfonium and surface them in the web UI + Subsonic responses.

**Current state:**
- Subsonic `setRating` endpoint exists but is a no-op (accepts and ignores)
- `getRating` not implemented — Subsonic browsing responses don't include `userRating`
- Track model has no `rating` column
- Symfonium sends `setRating?id=xxx&rating=3` when user rates a track

**What's needed:**

1. **Migration**: Add `rating INTEGER` column to `tracks` table (nullable, 0-5 where 0 = unrated)
2. **setRating endpoint**: Store the rating value on the track
3. **Subsonic responses**: Include `userRating` attribute in track/song XML/JSON (getAlbum, search, getRandomSongs, etc.)
4. **Web UI**: Show star rating on track cards/list rows, allow clicking to rate
5. **API**: `PUT /api/tracks/{id}` already handles metadata — add `rating` field

**Backend changes:**
- `backend/models/track.py`: add `rating = Column(Integer, nullable=True)`
- `backend/subsonic/annotation.py`: `set_rating` — parse `id` + `rating` params, update track
- `backend/subsonic/responses.py` (or wherever song XML is built): include `userRating` attr
- Alembic migration for the new column

**Frontend changes:**
- Library track list/grid: clickable star rating (1-5 stars, click to set, click again to clear)
- Track detail/edit modal: rating display + edit
- Sortable/filterable by rating (library page)
- Favorites page could show ratings alongside starred tracks

**Subsonic API reference:**
- `setRating(id, rating)` — rating is 1-5, or 0 to remove
- Song responses include `userRating` attribute (integer 1-5)
- `getStarred` returns starred items — ratings are separate from stars

**Implementation order:**
1. Alembic migration: add `rating` column to tracks
2. Update `setRating` endpoint to actually persist
3. Include `userRating` in all Subsonic song/child responses
4. Frontend: star rating component on library tracks
5. Frontend: filter/sort by rating

**Complexity: LOW-MEDIUM** — one column, one endpoint fix, response updates, small UI component. ~1 session.

---

## Low Priority

### Christmas Auto-Playlist
Seasonal playlist feature — detect Christmas/holiday tracks in library and manage them as a toggleable collection.

**Backend:**
- New scheduled task `playlist_christmas` (manual trigger only, not auto-scheduled)
- Detection logic: scan track titles, album names, and genres for Christmas keywords
  - Keywords: "christmas", "xmas", "holiday", "jingle", "silent night", "santa", "rudolph", "snowman", "winter wonderland", "let it snow", "deck the halls", "carol", "noel", etc.
  - Also match genre tags: "Christmas", "Holiday", "Xmas"
- Create/rebuild a "Christmas" playlist from matched tracks
- Add a `seasonal` flag or tag system so tracks can be included/excluded from normal rotation
- Config option: `[playlists] christmas_enabled = false` — when enabled, Christmas playlist appears; when disabled, it's hidden from Subsonic clients (Symfonium won't show it)

**Frontend:**
- Toggle on Playlists page or Schedule page: "Christmas Mode" on/off switch
- When enabled: shows Christmas playlist, optionally auto-generates on library scan
- Visual: snowflake icon, festive accent color

**Subsonic integration:**
- When christmas_enabled is false, exclude the Christmas playlist from getPlaylists response
- This lets users toggle seasonal music visibility in Symfonium without deleting tracks

**Implementation order:**
1. Add keyword detection function in `backend/services/playlists.py`
2. Add `playlist_christmas` scheduled task handler
3. Add config toggle
4. Add UI toggle + ScheduleControl
5. Filter Subsonic playlist response based on toggle
