# Zonik-mobile ↔ Zonik backend coupling survey

Branch: `feat/mobile-coupling`
Mobile source surveyed: `/home/spider/zonik-app` (Kotlin, Retrofit + kotlinx.serialization)
Backend source surveyed: `backend/subsonic/*` and `backend/api/*` on `main`.

Auth pattern: token (`u` + `t` + `s` + `v` + `c` + `f=json`), where `t = md5(apiKey + s)`.
Mobile sends `c=ZonikApp`, `v=1.16.1`. The interceptor lives in
`SubsonicAuthInterceptor.kt` and stamps every Subsonic request automatically.

## Subsonic endpoints

Status legend:

- OK — implemented and shape matches what the mobile parses.
- OK*  — implemented but the mobile parses the wrong response key (mobile bug).
- BUG-FIXED — fixed in this branch.
- STUB — endpoint returns a structurally valid empty response (no real data).

| Endpoint | Mobile call site | Backend handler | Status | Notes |
|----------|-----------------|-----------------|--------|-------|
| `rest/ping.view` | `SubsonicApi.ping`, login probe | `subsonic/system.py:ping` | OK | |
| `rest/getArtists.view` | `getArtists` (sync) | `subsonic/browsing.py:get_artists` | OK | Index buckets by first letter, returns `albumCount` + `coverArt`. |
| `rest/getArtist.view` | `getArtistDetail` | `subsonic/browsing.py:get_artist` | OK | Returns artist + albums. |
| `rest/getAlbum.view` | `getAlbumDetail` | `subsonic/browsing.py:get_album` | OK | Includes track list with full Subsonic Track shape. |
| `rest/getAlbumList2.view` | `getMostPlayedAlbums (frequent)`, `getRecentlyPlayedAlbums (recent)` | `subsonic/lists.py:get_album_list2` | BUG-FIXED | Previously `frequent` and `recent` both ordered by `created_at` (TODO comment). Now: `frequent` aggregates `tracks.play_count` per album (excludes albums with 0 plays); `recent` orders by max `tracks.last_played_at` per album. |
| `rest/search3.view` | `search`, fast-sync (`syncArtists`/`syncAlbums`/`syncAllTracks`) | `subsonic/search.py:search3` | OK | Empty-query fast-sync supported. |
| `rest/getRandomSongs.view` | `getRandomSongs` (radio fallback) | `subsonic/lists.py:get_random_songs` | OK | |
| `rest/getGenres.view` | `getGenres` | `subsonic/browsing.py:get_genres` | OK | |
| `rest/getPlaylists.view` | `getPlaylists` | `subsonic/playlists_api.py:get_playlists` | OK | |
| `rest/getPlaylist.view` | `getPlaylistTracks` | `subsonic/playlists_api.py:get_playlist` | OK | |
| `rest/getStarred2.view` | `syncAllTracks` (authoritative starred) | `subsonic/lists.py:get_starred2` | OK | |
| `rest/star.view` | `star` | `subsonic/annotation.py:star` | OK | Supports id / albumId / artistId. |
| `rest/unstar.view` | `unstar` | `subsonic/annotation.py:unstar` | OK | |
| `rest/scrobble.view` | `PlaybackManager.checkScrobble` (>50% played, `submission=true`) and `scrobbleNowPlaying` (`submission=false`) | `subsonic/annotation.py:scrobble` | BUG-FIXED | Three pre-existing bugs: (1) POST body wasn't parsed (mobile uses GET, but spec allows POST), (2) `submission` only matched the literal string `"true"` (case-sensitive), (3) `time` parameter was ignored. All three fixed. Mobile sends GET, lower-case `true`, no `time` so behavior was correct in the common path — but offline-flushed scrobbles now retry-time-shift to the server. See `time` recommendation below. |
| `rest/setRating.view` | `markForDeletion` (rating=1), `unmarkForDeletion` (rating=0) | `subsonic/annotation.py:set_rating` | OK | Mobile uses rating=1 as "delete me" sentinel — interesting convention, works. |
| `rest/getSimilarSongs2.view` | `getSimilarSongs` (radio) | `subsonic/browsing.py:get_similar_songs2` | OK | Embedding-based with artist/genre fallback. |
| `rest/getSongsByGenre.view` | radio fallback (`startRadio`) | `subsonic/lists.py:get_songs_by_genre` | OK* | Backend returns `{"songsByGenre": {"song": [...]}}` per Subsonic spec. Mobile parses it as `RandomSongsResponse` and looks for `randomSongs.song` — so the mobile *currently always gets an empty list from this endpoint*. The genre fallback in `LibraryRepository.startRadio` is silently dead. Mobile bug, not backend. |
| `rest/stream.view` | `PlaybackManager.buildStreamUrl`, `OfflineCacheManager`, `WaveformManager`, `ZonikMediaService` | `subsonic/media.py:stream` | OK | Transcode cache, ffmpeg, range support tuned for Mobile (see commit `cb1582e`). |
| `rest/getCoverArt.view` | `CoverArtProvider`, `PlaybackManager.buildArtUrl` | `subsonic/media.py:get_cover_art` | OK | Resize cache, corrupt-source cleanup. |
| `rest/getLyrics.view` | not called yet | `subsonic/system.py:get_lyrics` | STUB (new) | Added so Symfonium/other clients can probe it without 404. Returns empty value. |
| `rest/getLyricsBySongId.view` | not called yet | `subsonic/system.py:get_lyrics_by_song_id` | STUB (new) | OpenSubsonic spec endpoint. Returns empty `structuredLyrics`. Removed `songLyrics` from advertised extensions to be honest about lack of lyric data. |

### Subsonic endpoints implemented but unused by the mobile (kept available)

These work and a future mobile feature can adopt them:

- `getMusicFolders`, `getIndexes`, `getMusicDirectory`, `getSong`
- `getArtistInfo2` — populated from `artists.biography` + `image_url` + `musicbrainz_id`
- `getTopSongs` — orders by `tracks.play_count`
- `getNowPlaying` — returns the in-process map keyed off `submission=false` scrobbles
- `getUser`
- `getBookmarks`, `createBookmark`, `deleteBookmark`
- `getPlayQueue`, `savePlayQueue`
- `createPlaylist`, `updatePlaylist`, `deletePlaylist`

### Custom Zonik (non-Subsonic) endpoints used by the mobile

| Endpoint | Mobile call site | Backend handler | Status |
|----------|-----------------|-----------------|--------|
| `POST /api/download/search` | `searchDownloads` | `backend/api/download.py` | OK (managed by parallel branch) |
| `POST /api/download/trigger`, `bulk`, `cancel-transfer` | various | `backend/api/download.py` | OK (parallel) |
| `GET /api/download/status` | download polling | `backend/api/download.py` | OK (parallel) |
| `POST /api/logs` | `LogUploader.uploadLogsToServer` | `backend/api/app_logs.py` | OK |
| `GET /api/jobs/active`, `GET /api/jobs`, `GET /api/jobs/{id}` | Jobs UI | `backend/api/jobs.py` | OK (parallel) |
| `POST /api/tracks/bulk-delete` | bulk delete | `backend/api/tracks.py` | OK |
| `POST /api/pair`, `GET /api/pair/{code}` | pairing flow on login | `backend/api/pair.py` | OK |
| `GET /api/tracks/{id}/waveform?bars=N` | `WaveformManager` | `backend/api/tracks.py` | OK |
| `GET /app` | (server-side; redirects to GitHub APK) | `backend/main.py` | OK |

## Auth gap (informational, not in scope of this PR)

`/rest/*` is registered without applying `authenticate_subsonic()` as a
dependency. Each endpoint is responsible for resolving the user from the `u`
parameter, defaulting to `"admin"` if absent. There is no token verification
anywhere on the public Subsonic surface — anyone who can reach the server can
read or scrobble. The mobile's auth interceptor still sends valid `t`/`s`, so
correctness for the mobile is unaffected. Worth tracking as a separate hardening
PR; do *not* fix here without coordinating with the frontend, which also speaks
Subsonic.

## Schema fields that the mobile reads

These are derived by reading `model/SubsonicResponse.kt`. Anything the backend
populates that isn't on this list is harmless (kotlinx.serialization ignores
unknown keys via the global `ignoreUnknownKeys = true`).

- Track: `id, title, artist, artistId, album, albumId, coverArt, duration,
  track, year, genre, bitRate, size, suffix, contentType, transcodedSuffix,
  transcodedContentType, path, starred, userRating`
- Album: `id, name, artist, artistId, coverArt, year, songCount, duration,
  genre, starred`
- Artist: `id, name, albumCount, coverArt, starred`
- Playlist: `id, name, songCount, duration, coverArt, owner`
- Genre: `value, songCount, albumCount`

The backend's `format_track`, `format_album`, `format_artist` cover all of
these. `userRating` is used by the mobile as a "marked-for-deletion" flag
(rating==1), which is preserved by `setRating`. Note: mobile does NOT read
`playCount` or `played` even though the backend emits them — could be surfaced
in a future stats screen.

## Recommended Zonik-mobile-side changes

1. **Fix `getSongsByGenre` parsing.** `LibraryRepository.startRadio` calls
   `api.getSongsByGenre(genre, 50).response.randomSongs?.song`, but the Subsonic
   spec (and Zonik backend) wraps the result in `songsByGenre`. Add a
   `SongsByGenreResponse` envelope to `SubsonicResponse.kt` and update
   `SubsonicApi.getSongsByGenre` to return it. Until fixed, the genre fallback
   in `startRadio` always returns an empty list.

2. **Send `time` with offline-flushed scrobbles.** `PendingScrobbleEntity`
   already stores `timestamp: Long` (millis since epoch), but
   `flushPendingScrobbles` calls `libraryRepository.scrobble(trackId)` without
   it, so the server records the *flush* time as the play time. Add an
   overload `scrobble(id: String, time: Long? = null)` in `SubsonicApi` mapped
   to `@Query("time")`, and pass `entity.timestamp` when flushing. The backend
   now honours `time` after this branch's scrobble fix.

3. **Use POST scrobble (optional).** Spec allows POST and the backend now
   parses form bodies. Long URLs aren't a problem here, so this is just
   future-proofing for clients that prefer POST.

4. **Surface `playCount` / `played` from the backend.** Both are returned by
   `format_track` and the mobile's `Models.Track` already extends easily.
   Sorting "Recently Played" or showing per-track play counts in stats becomes
   trivial. Same for albums (could add `playCount` to album response by
   summing — easy follow-up).

5. **Adopt `getNowPlaying`.** Could be a fun "what's everyone playing" surface
   for multi-user setups. Backend already implemented.

6. **Consider playQueue sync.** `getPlayQueue`/`savePlayQueue` are wired up;
   would let the mobile resume on a different device. Currently the mobile
   only persists locally to DataStore.

7. **Bookmarks.** `getBookmarks`/`createBookmark` work — could be used for
   long-form audio (podcasts, mixes). Not relevant for typical music playback,
   filing as nice-to-have.

## Things explicitly skipped

- `/api/jobs/*`, `/api/download/*`, soulseek client, `models/job.py` —
  parallel branch territory per the task spec.
- Frontend (`frontend/`) — out of scope.
- Subsonic auth hardening — needs to land alongside frontend changes; calling
  it out for a follow-up PR.
- Real lyrics ingestion — would need scanner + storage + LRC support, much
  larger scope.
