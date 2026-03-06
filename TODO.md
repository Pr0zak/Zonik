# Zonik TODO

## Medium Priority

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
- Discover page: new "Remixes" tab or sub-section
- Per-track "Find Remixes" button in library context menu (3-dot menu)
- Results table: Track, Artist, Version Type, Status (in library / download)
- Bulk download missing remixes

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
