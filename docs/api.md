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
| `/api/library/scan` | POST | Trigger library scan |
| `/api/library/recent?limit=` | GET | Recently added tracks |
| `/api/library/genres` | GET | Genre list with counts |

### Tracks

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tracks/` | GET | List tracks with pagination |
| `/api/tracks/{id}` | GET | Track details |
| `/api/tracks/{id}` | DELETE | Delete track |
| `/api/tracks/search?q=` | GET | Search tracks |

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
| `/api/discovery/lastfm/auth-url` | GET | Last.fm OAuth URL |
| `/api/discovery/lastfm/callback?token=` | GET | Exchange token for session |

### Favorites

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/favorites/` | GET | List favorites |
| `/api/favorites/star` | POST | Star item `{track_id?, album_id?, artist_id?}` |
| `/api/favorites/unstar` | POST | Unstar item |

### Playlists

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/playlists/` | GET | List playlists |
| `/api/playlists/` | POST | Create playlist |
| `/api/playlists/{id}` | GET | Playlist details |
| `/api/playlists/{id}` | PUT | Update playlist |
| `/api/playlists/{id}` | DELETE | Delete playlist |

### Analysis

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analysis/status` | GET | Analysis queue status |
| `/api/analysis/analyze` | POST | Queue tracks for analysis |
| `/api/analysis/echo-match` | POST | Vibe similarity search `{track_id, limit?}` |
| `/api/analysis/vibe-search` | POST | Text-to-audio search `{query, limit?}` |

### Config

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config/services` | GET | Get service connection settings (keys masked) |
| `/api/config/services` | PUT | Update service connections `{slskd_url, slskd_api_key, lidarr_url, lidarr_api_key, lastfm_api_key, lastfm_write_api_key, lastfm_write_api_secret}` |

### Schedule

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/schedule/` | GET | List scheduled tasks |
| `/api/schedule/{name}` | PUT | Update task config |
| `/api/schedule/{name}/run` | POST | Run task immediately |

### Jobs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/jobs/` | GET | Job history |
| `/api/jobs/{id}` | GET | Job details |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `ws:///api/ws` | Real-time job progress updates |
