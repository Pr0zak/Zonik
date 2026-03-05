# API Reference

## Subsonic / OpenSubsonic API

Base URL: `/rest`

All endpoints support both `/endpoint` and `/endpoint.view` URL patterns. Authentication via `u` (username) + `t` (token) + `s` (salt) query parameters, or `u` + `p` (password).

### System

| Endpoint | Description |
|----------|-------------|
| `GET /rest/ping` | Server health check |
| `GET /rest/getLicense` | License info (always valid) |
| `GET /rest/getOpenSubsonicExtensions` | Supported OpenSubsonic extensions |

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
| `GET /rest/getSimilarSongs2?id=&count=` | Similar songs (vibe or fallback) |
| `GET /rest/getTopSongs?artist=&count=` | Top songs by artist |

### Lists

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getAlbumList2?type=&size=&offset=` | Album lists (newest, random, starred, etc.) |
| `GET /rest/getRandomSongs?size=&genre=` | Random tracks |
| `GET /rest/getSongsByGenre?genre=&count=&offset=` | Tracks by genre |
| `GET /rest/getStarred2` | All starred items |

### Search

| Endpoint | Description |
|----------|-------------|
| `GET /rest/search3?query=` | Search artists, albums, tracks. Empty query = fast sync for Symfonium |

### Media

| Endpoint | Description |
|----------|-------------|
| `GET /rest/stream?id=` | Stream audio (supports `maxBitRate`, `format`, `timeOffset` for transcoding) |
| `GET /rest/download?id=` | Download original file |
| `GET /rest/getCoverArt?id=` | Cover art image |

### Annotation

| Endpoint | Description |
|----------|-------------|
| `GET /rest/star?id=&albumId=&artistId=` | Star items |
| `GET /rest/unstar?id=&albumId=&artistId=` | Unstar items |
| `GET /rest/scrobble?id=` | Record play |
| `GET /rest/setRating?id=&rating=` | Set rating |

### Playlists

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getPlaylists` | All playlists |
| `GET /rest/getPlaylist?id=` | Playlist with tracks |
| `GET /rest/createPlaylist` | Create/update playlist |
| `GET /rest/updatePlaylist` | Update playlist metadata |
| `GET /rest/deletePlaylist?id=` | Delete playlist |

### Bookmarks & Play Queue

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getBookmarks` | All bookmarks |
| `GET /rest/createBookmark?id=&position=` | Create bookmark |
| `GET /rest/deleteBookmark?id=` | Delete bookmark |
| `GET /rest/getPlayQueue` | Get saved play queue |
| `GET /rest/savePlayQueue` | Save play queue |

### Users

| Endpoint | Description |
|----------|-------------|
| `GET /rest/getUser?username=` | User info |

## Zonik REST API

Base URL: `/api`

### Library

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/library/stats` | GET | Basic library counts |
| `/api/library/stats/detailed` | GET | Detailed stats with breakdowns |
| `/api/library/scan` | POST | Trigger library scan (returns `{job_id}`) |
| `/api/library/recent?limit=` | GET | Recently added tracks |
| `/api/library/artists?offset=&limit=&search=&sort=&order=` | GET | List artists with cover art and track counts |
| `/api/library/albums?offset=&limit=&search=&sort=&order=&artist_id=` | GET | List albums with artist and cover art |
| `/api/library/genres` | GET | Genre list with counts |

### Tracks

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tracks?offset=&limit=&sort=&order=&search=&genre=&artist_id=&album_id=` | GET | List tracks with pagination, filtering. Search uses FTS5 (title, artist, album) with ILIKE fallback |
| `/api/tracks/{id}` | GET | Track details with analysis |
| `/api/tracks/{id}` | PUT | Update track metadata `{title?, genre?, year?, track_number?}` (also writes file tags) |
| `/api/tracks/{id}` | DELETE | Delete track and file |
| `/api/tracks/bulk-delete` | POST | Bulk delete `{track_ids: [...]}` |
| `/api/tracks/bulk-analyze` | POST | Queue bulk analysis `{track_ids: [...]}` |

### Downloads

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/download/search` | POST | Soulseek search `{artist, track}` |
| `/api/download/trigger` | POST | Download track `{artist, track, username?, filename?}` |
| `/api/download/bulk` | POST | Bulk download `{tracks: [{artist, track}]}` |
| `/api/download/status` | GET | slskd download status |
| `/api/download/blacklist` | GET | List blacklisted items |
| `/api/download/blacklist` | POST | Add to blacklist `{artist, track?, reason?}` |
| `/api/download/blacklist/{id}` | DELETE | Remove from blacklist |

### Discovery

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/discovery/top-tracks?limit=&page=` | GET | Last.fm chart with library status |
| `/api/discovery/similar-tracks?limit=` | GET | Similar to favorites |
| `/api/discovery/similar-artists?limit=` | GET | Similar artists |
| `/api/discovery/top-albums?artist=` | GET | Artist top albums |
| `/api/discovery/track-info?artist=&track=` | GET | Last.fm track info |
| `/api/discovery/artist-info?artist=` | GET | Last.fm artist info |
| `/api/discovery/similar-by-track?artist=&track=&limit=` | GET | Similar tracks to a specific track via Last.fm (with library status) |
| `/api/discovery/lastfm/auth-url` | GET | Last.fm OAuth URL |
| `/api/discovery/lastfm/callback?token=` | GET | Exchange token for session |

### Favorites

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/favorites` | GET | List favorites with track/album/artist details |
| `/api/favorites/ids` | GET | Favorite IDs for quick lookup `{track_ids, album_ids, artist_ids}` |
| `/api/favorites/star` | POST | Star item `{track_id?, album_id?, artist_id?}` |
| `/api/favorites/unstar` | POST | Unstar item `{track_id?, album_id?, artist_id?}` |
| `/api/favorites/import` | POST | Bulk import `{tracks: [{title, artist, file_path?}]}` |

### Playlists

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/playlists/` | GET | List playlists |
| `/api/playlists/` | POST | Create playlist |
| `/api/playlists/generate` | POST | Smart playlist `{name, rule, value?, limit?}` |
| `/api/playlists/{id}` | GET | Playlist details |
| `/api/playlists/{id}` | PUT | Update playlist |
| `/api/playlists/{id}` | DELETE | Delete playlist |

### Analysis

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/stats` | GET | Analysis coverage statistics |
| `/api/analysis/start` | POST | Queue unanalyzed tracks for audio analysis `{force?}` |
| `/api/analysis/embeddings/start` | POST | Queue tracks for CLAP vibe embeddings `{force?}` |
| `/api/analysis/enrich` | POST | Run metadata enrichment (genre, cover art) on all tracks missing data |
| `/api/analysis/echo-match` | POST | Vibe similarity search `{track_id, limit?}` |
| `/api/analysis/vibe-search` | POST | Text/track vibe search `{query?, track_id?, limit?}` |
| `/api/analysis/steady-vibes` | POST | Steady Vibes playlist from seed `{seed_track_id, length?}` |
| `/api/analysis/track/{id}` | GET | Track analysis details (BPM, key, energy, etc.) |

### Config

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config/services` | GET | Get service connection settings (keys masked) |
| `/api/config/services` | PUT | Update service connections and directories |
| `/api/config/test/{service}` | POST | Test service connectivity (`lastfm`, `soulseek`, `lidarr`) |
| `/api/config/version` | GET | Current version and git commit hash |
| `/api/config/updates` | GET | Check GitHub for updates (5-min cache) |
| `/api/config/upgrade` | POST | Trigger upgrade via `upgrade.sh` (returns `{job_id}`) |
| `/api/config/health` | GET | System health check (database, Redis, slskd, Last.fm, Lidarr) |
| `/api/config/backup` | POST | Create database backup |
| `/api/config/backups` | GET | List available backups |
| `/api/config/restore/{filename}` | POST | Restore from backup |

### Users

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/users/` | GET | List users |
| `/api/users/` | POST | Create user `{username, password, is_admin?}` |
| `/api/users/{id}/password` | PUT | Change password `{password}` |
| `/api/users/{id}` | DELETE | Delete user |

### Schedule

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/schedule/` | GET | List scheduled tasks (includes label, description, config, last_run_at) |
| `/api/schedule/{name}` | PUT | Update task config `{enabled?, interval_hours?, run_at?, day_of_week?}` |
| `/api/schedule/{name}/run` | POST | Run task immediately |

Available scheduled tasks:

| Task Name | Description |
|-----------|-------------|
| `library_scan` | Scan the music directory for new, changed, or removed files |
| `enrichment` | Fetch missing genre tags and cover art from MusicBrainz, Deezer, etc. |
| `audio_analysis` | Run Essentia audio analysis (BPM, key, energy, danceability) on unanalyzed tracks |
| `lastfm_top_tracks` | Pull Last.fm top chart and flag tracks not in library |
| `discover_similar` | Find tracks similar to favorites using Last.fm |
| `discover_artists` | Discover new artists related to those in your library |
| `lastfm_sync` | Sync loved tracks and scrobble history with Last.fm |
| `playlist_weekly_top` | Auto-generate playlist of chart tracks found in library |
| `playlist_weekly_discover` | Auto-generate discovery playlist with random library mix |
| `playlist_favorites` | Rebuild Favorites playlist from all starred tracks |
| `kimahub_favorites_sync` | Import liked tracks from KimaHub PostgreSQL into favorites |
| `library_cleanup` | Remove orphaned database entries for deleted files |

### Jobs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs/` | GET | Job history |
| `/api/jobs/active` | GET | Currently running jobs |
| `/api/jobs/stream/recent?limit=` | GET | Recent job updates for live display |
| `/api/jobs/{id}` | GET | Job details (result, log, tracks) |
| `/api/jobs/{id}/retry` | POST | Retry failed download job |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `ws:///api/ws` | Real-time job progress updates |

WebSocket messages use the following format:

```json
{
  "id": "job-uuid",
  "type": "download",
  "status": "running",
  "progress": 3,
  "total": 10
}
```

- `type`: Job type (e.g. `download`, `scan`, `analysis`, `upgrade`)
- `status`: One of `running`, `completed`, `failed`
- `progress` / `total`: Numeric progress for bulk operations (e.g. 3 of 10 tracks downloaded)

**Download retry behavior**: When downloading via Soulseek, `search_and_download` tries up to 5 candidates (sorted by quality score) before marking the job as failed. Each candidate attempt uses the 4-strategy search fallback.
