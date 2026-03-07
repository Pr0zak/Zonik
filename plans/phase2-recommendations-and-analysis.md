# Phase 2: Recommendations, Embeddings & Analysis

## Overview
Five enhancements across recommendation workflow, taste profiling, and audio analysis coverage.

---

## Task 1: Download All Recommendations
**Impact: MEDIUM** — Bulk download top-scored or filtered recommendations in one click.

### Backend
- `POST /api/recommendations/bulk-download` — accepts `mode` param:
  - `top_N` (default 20): download top N by score
  - `above_score` (threshold, e.g. 0.7): download all above score X
- Filters to `status=pending` only (skip already downloaded/rejected)
- For each rec: call existing `/api/download/trigger` logic, mark rec as `downloaded`
- Creates a `bulk_download` Job with per-track progress (reuse `_auto_download_missing` pattern from scheduler.py)

### Frontend (Discover > For You tab)
- Add dropdown button next to "AI Suggestions": "Download Top 20" / "Download Score > 0.7"
- Show spinner while bulk download runs
- Update rec statuses in UI as they complete

### Files to modify
| File | Changes |
|------|---------|
| `backend/api/recommendations.py` | New `bulk-download` endpoint |
| `frontend/src/routes/discover/+page.svelte` | Dropdown button + handler |

---

## Task 2: Last.fm User History for Taste Profile
**Impact: HIGH** — Enrich taste profile with scrobble data from all devices (Symfonium, car, etc.), not just local play counts.

### Backend
- New function `_fetch_lastfm_history(username, api_key)` in `recommender.py`:
  - `user.getTopArtists(period=6month, limit=50)` — weighted artist affinity
  - `user.getTopTracks(period=6month, limit=100)` — listening patterns
- New Last.fm API methods in `lastfm.py`:
  - `get_user_top_artists(username, period, limit)`
  - `get_user_top_tracks(username, period, limit)`
- Merge into `build_taste_profile()`:
  - Blend local play_count artists with Last.fm top artists (weighted merge)
  - Add `lastfm_top_artists` and `lastfm_top_tracks` to profile_data JSON
  - Use Last.fm play counts as additional artist_affinity signal in scoring
- Only active when `session_key` + `username` exist in config

### Frontend
- No UI changes needed — taste profile auto-enriched during recommendation refresh
- Optional: show "Last.fm connected" badge on For You tab header

### Files to modify
| File | Changes |
|------|---------|
| `backend/services/lastfm.py` | Add `get_user_top_artists()`, `get_user_top_tracks()` |
| `backend/services/recommender.py` | Fetch Last.fm history, merge into taste profile + scoring |

---

## Task 3: Recommendation Stats Dashboard
**Impact: MEDIUM** — Show conversion funnel and recommendation effectiveness.

### Backend
- `GET /api/recommendations/stats` endpoint returning:
  - `total_generated` — all-time recommendation count
  - `total_downloaded` — status=downloaded count
  - `total_thumbs_up` / `total_thumbs_down` — feedback counts
  - `by_source` — breakdown by source type (similar_track, similar_artist, tag, trending, claude)
  - `avg_score` — average score of downloaded vs rejected
  - `top_sources` — which sources produce most downloads
  - `recent_activity` — last 10 feedback/download actions with timestamps

### Frontend (Discover > For You tab)
- Stats bar above recommendation list:
  - "142 recommended -> 38 downloaded -> 24 liked" with colored numbers
  - Small source breakdown pills (e.g. "Similar: 45%, Artists: 30%, AI: 25%")
- Compact horizontal layout, doesn't take much vertical space

### Files to modify
| File | Changes |
|------|---------|
| `backend/api/recommendations.py` | New `/stats` endpoint |
| `frontend/src/routes/discover/+page.svelte` | Stats bar UI |

---

## Task 4: CLAP Vibe Embeddings Setup
**Impact: HIGH** — Enable vibe search ("chill sunset vibes") and improve recommendation CLAP similarity scoring. Currently 0/1057 tracks have embeddings.

### Investigation needed
- Check if CLAP model downloads on first run or needs manual setup
- Check CT 228 disk space + RAM for model (~600MB)
- Test embedding generation for a few tracks to verify it works

### Backend fixes (if needed)
- Ensure `enable_clap: true` in config
- Test `/api/analysis/embeddings/start` endpoint
- Verify embedding generation completes without hanging (same pool resilience as Essentia)
- CLAP uses librosa + transformers — different from Essentia, runs in main process or thread pool

### Frontend
- Already has the Vibe Embeddings card + "Generate Embeddings" button
- Already has vibe search UI with text input
- Should just work once embeddings are generated

### Files to check/modify
| File | Changes |
|------|---------|
| `backend/services/embeddings.py` | Verify model loading, add error handling |
| `backend/api/analysis.py` | Check embeddings/start endpoint resilience |
| Production config | Enable CLAP if disabled |

---

## Task 5: Opus Analysis Support
**Impact: MEDIUM** — 507 tracks (48% of library) currently skipped. Opus is increasingly common.

### Options (ranked by feasibility)

**Option A: FFmpeg pre-conversion (recommended)**
- Before Essentia analysis, convert .opus to temporary .wav via ffmpeg subprocess
- Analyze the .wav, delete temp file
- Essentia handles .wav perfectly — no segfault risk
- Adds ~2-3s per track but only for opus files
- ffmpeg already installed on CT 228

**Option B: Alternative analyzer for opus**
- Use librosa (already installed for CLAP) to extract features
- librosa can load opus via soundfile/audioread
- Would need to replicate Essentia's BPM/key/energy/danceability extraction
- More work, less accurate than Essentia

**Option C: Build Essentia with opus support**
- Requires compiling from source with proper FFmpeg/opus libs
- Fragile, hard to maintain across upgrades
- Not recommended

### Implementation (Option A)
- In `analyze_track()`, if extension is `.opus`:
  1. Convert to temp .wav: `ffmpeg -i input.opus -ar 44100 -ac 1 temp.wav`
  2. Run Essentia on temp.wav
  3. Delete temp.wav
- Add `.opus` to ESSENTIA_SUPPORTED_EXTENSIONS
- Add timeout guard (30s for conversion + 120s for analysis)

### Files to modify
| File | Changes |
|------|---------|
| `backend/services/analyzer.py` | Add opus→wav conversion, update extensions |

---

## Build Order

1. **Task 3: Recommendation Stats** (frontend-only + simple endpoint, quick win)
2. **Task 1: Download All Recommendations** (reuses existing download infra)
3. **Task 2: Last.fm User History** (backend enrichment, no UI needed)
4. **Task 5: Opus Analysis** (ffmpeg conversion approach)
5. **Task 4: CLAP Embeddings** (investigation + model setup on production)

## Verification
- `uv run python -m py_compile` for each modified Python file
- `cd frontend && npx svelte-check --threshold error`
- Deploy to CT 228, test each feature
- For opus: run analysis, verify opus tracks now get BPM/key/energy
- For CLAP: check `/api/analysis/stats` shows `with_embeddings > 0`
