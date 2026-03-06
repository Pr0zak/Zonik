# Zonik TODO

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
