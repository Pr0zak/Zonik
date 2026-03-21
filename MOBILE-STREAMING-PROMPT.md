# Zonik Server Streaming Enhancements v2 — Client Adaptation

The Zonik server has been updated with major streaming improvements. Adapt the Zonik-mobile client to take full advantage.

## What Changed Server-Side

### 1. Transcode Cache (NEW)

The server now caches transcoded output to disk. When a track is transcoded at a given format+bitrate, subsequent requests for the same combination serve from cache via `FileResponse` — meaning:

- **Full range request support on cached transcodes** (206 Partial Content, Content-Range, ETag, Accept-Ranges: bytes)
- **Instant response** on cache hit (no ffmpeg startup latency)
- Cache is keyed by `{track_id}_{format}_{bitrate}`; invalidated when source file changes

**Client action**: Pre-cache downloads will be dramatically faster on second play. Ensure ExoPlayer handles the transition from `StreamingResponse` (first play) to `FileResponse` (cached, with range support) gracefully — the response characteristics change between first and subsequent requests for the same track+bitrate.

### 2. Concurrent Transcode Limits (NEW)

The server now limits concurrent ffmpeg processes (default: 3). Additional requests queue via backpressure — they wait rather than getting rejected.

**Client action**:
- Pre-cache downloads may take longer to start when many are queued. Ensure the client has reasonable timeouts (30s+ connect timeout for stream requests)
- Don't cancel and retry pre-cache requests that haven't started yet — they're just waiting in the queue
- Consider reducing concurrent pre-cache from 10 to 5-6 to avoid excessive queuing

### 3. FFmpeg Error Logging (NEW)

The server now captures and logs ffmpeg stderr on non-zero exit. No client changes needed, but if you see transcoding failures (empty responses), check server logs for diagnostics.

### 4. Cover Art Resizing (NEW)

The `getCoverArt` endpoint now supports the `size` query parameter (OpenSubsonic standard):

```
/rest/getCoverArt.view?id=COVER_ID&size=300
```

- Images are resized server-side with Pillow (LANCZOS resampling, JPEG quality 85)
- Resized versions are cached on disk
- Maximum size capped at 1200px
- Original served if `size` is omitted

**Client action**:
- **Always pass `size` parameter** matching the display size. For list thumbnails use `size=100`, for now-playing use `size=600`, for full-screen use `size=900`
- This dramatically reduces bandwidth — a 3000x3000 cover art (2MB JPEG) becomes 300x300 (30KB)
- The response is always JPEG regardless of original format

### 5. Gapless Playback Metadata (NEW)

Track responses for lossless files (FLAC, WAV, ALAC, AIFF) now include:

```json
{
  "transcodedSuffix": "mp3",
  "transcodedContentType": "audio/mpeg"
}
```

**Client action**:
- Use `transcodedSuffix` and `transcodedContentType` to configure ExoPlayer's decoder pipeline before playback starts
- When these fields are present, the client knows the server will transcode to MP3 — set up the MP3 decoder for gapless playback
- When absent, the track will be served in its original format (`suffix` / `contentType` fields)

### 6. Estimated Content-Length (NEW)

When `estimateContentLength=true` is passed on stream requests, the server now returns an estimated `Content-Length` header for transcoded streams:

```
/rest/stream.view?id=TRACK_ID&maxBitRate=192&estimateContentLength=true
```

Formula: `(remaining_duration_seconds * bitrate * 1000) / 8`

**Client action**:
- Pass `estimateContentLength=true` on all stream requests (you may already be doing this)
- ExoPlayer uses Content-Length for buffer percentage calculations and download progress
- The estimate may be slightly off (CBR assumption on VBR-encoded output), but it's much better than no Content-Length at all

### 7. FFmpeg Threading Control (NEW)

Each ffmpeg transcode now runs with `-threads 1` to prevent thread sprawl. Combined with the concurrent limit of 3, this means max 3 CPU threads for transcoding. No client changes needed.

### 8. HEAD Request Support (NEW)

Stream, download, and cover art endpoints now support HTTP HEAD requests:

```
HEAD /rest/stream.view?id=TRACK_ID&u=admin&p=admin
HEAD /rest/getCoverArt.view?id=COVER_ID
```

- For direct file serves: returns full headers (Content-Length, ETag, Accept-Ranges) without body
- For transcoded streams: returns estimated Content-Length (if available) and content type

**Client action**:
- ExoPlayer may already send HEAD requests for content probing — these now work instead of returning 405
- Can use HEAD to check file size before deciding whether to pre-cache (bandwidth-aware pre-caching)

### 9. Now Playing (NEW)

The server now tracks "now playing" state from scrobble notifications:

```
# Report now playing:
/rest/scrobble.view?id=TRACK_ID&submission=false&u=admin&p=admin

# Query now playing:
/rest/getNowPlaying.view?u=admin&p=admin
```

Response:
```json
{
  "nowPlaying": {
    "entry": [
      {
        "id": "...", "title": "...", "artist": "...",
        "username": "admin",
        "minutesAgo": 2,
        "playerId": "zonik-mobile"
      }
    ]
  }
}
```

- Entries expire after 10 minutes of no updates
- One entry per user (latest track wins)

**Client action**:
- Send `submission=false` scrobble when playback starts (you may already be doing this)
- Include `c=zonik-mobile` parameter to identify the client
- Optionally poll `getNowPlaying` to show what other users are listening to

## Previous Enhancements (Still Active)

These were added in v0.4.0 and remain in effect:

- **Range requests**: Full 206 support on all file-serving endpoints (via Starlette FileResponse)
- **Cache-Control**: streams 24h private, cover art 7d public
- **Low-latency transcode**: ffmpeg flush flags for faster first byte
- **Accept-Ranges: none**: on transcoded streams (use `timeOffset` for seeking)
- **Keep-alive**: 30 second timeout for connection reuse

## Updated Client Verification Checklist

- [ ] Pre-cache downloads resume correctly (range requests on cached transcodes)
- [ ] Cover art requests include `size` parameter (check network traffic for reduced payload sizes)
- [ ] `transcodedSuffix`/`transcodedContentType` parsed from track responses
- [ ] `estimateContentLength=true` passed on stream requests
- [ ] Connect timeout >= 30s on stream requests (backpressure from concurrent limit)
- [ ] `submission=false` scrobble sent on playback start with `c=zonik-mobile`
- [ ] HEAD requests work (no 405 errors in logs)
- [ ] No retry storms on queued transcode requests
- [ ] Second play of same track+bitrate is near-instant (cache hit)
