# Zonik TODO

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
