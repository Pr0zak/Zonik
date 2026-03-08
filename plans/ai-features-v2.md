# AI Features V2 — Enhanced AI Integration

## Overview
8 new AI-powered features, each independently toggleable in Settings > AI Assistant. All use Claude API via a shared client with rate limiting and token tracking.

## Architecture

### Shared Client (`backend/services/ai/client.py`)
- `async def call_claude(system: str, prompt: str, max_tokens: int = 4096, json_response: bool = True) -> dict`
- Rate limiting: `asyncio.Semaphore(2)` caps concurrent Claude calls
- Token usage tracking: accumulate input/output tokens, expose via `/api/config/ai-usage`
- Reuses `parse_response()` from existing `claude_ai.py`
- Config check: raises if `assistant.enabled` is False or API key missing

### Config Flags (`AssistantConfig` in config.py)
```python
ai_search: bool = False
ai_playlists: bool = False
ai_tagging: bool = False
ai_insights: bool = False
ai_duplicate_resolver: bool = False
ai_download_advisor: bool = False
ai_explanations: bool = False
ai_mood_tags: bool = False
```
All default False (opt-in). Each consumes Claude API tokens — user controls what they want.

### Settings UI
Expand AI Assistant card with toggle switches per feature. Each toggle shows a brief description + estimated cost hint. Features hidden from UI when disabled.

---

## Phase 1 — High Value

### 1A. Natural Language Search
**Daily-use feature. Transforms the search experience.**

**Backend:** `backend/services/ai/nl_search.py`
- `interpret_query(query, db)` — sends NL query to Claude with system prompt describing available filters (genre, BPM range, energy, danceability, year, artist, format, play_count, rating, date ranges). Claude returns structured JSON filter object.
- `search_by_embedding(query, db, limit=20)` — for mood/vibe queries, use CLAP text-to-audio similarity
- Detection heuristic: if query contains mood/temporal/descriptive words ("chill", "last week", "like X but Y", "find"), route to AI. Direct "Artist - Track" queries use FTS.

**API:** `POST /api/search/ai` — `{"query": str}` → `{"tracks": [...], "explanation": str, "method": "nl"|"embedding"|"fts"}`

**Frontend:** TopBar.svelte — detect NL queries, show sparkle icon, call AI endpoint, show explanation in results dropdown.

### 1B. AI Playlist Generation
**Direct value — creates tangible output (a real playlist).**

**Backend:** `backend/services/ai/playlist_gen.py`
- `generate_playlist(prompt, db, track_count=25)` — builds context (genre dist, top artists, sample of 200 tracks with metadata+analysis), Claude selects tracks, fuzzy-match to library, create Playlist record.
- CLAP fallback: for mood-based requests, generate text embedding of prompt, find nearest tracks.

**API:** `POST /api/playlists/ai-generate` — `{"prompt": str, "track_count": int, "name": str|null}`

**Frontend:** Playlists page — "AI Generate" button (Sparkles icon), modal with text prompt + track count slider.

### 1C. Enhanced "Why?" Explanations
**Low effort, high polish.**

**Backend:** `backend/services/ai/explainer.py`
- `explain_recommendation(rec_id, db)` — loads Recommendation + taste profile + score breakdown, Claude generates deep explanation with genre connections and similar artist reasoning.

**API:** `POST /api/recommendations/{id}/explain`

**Frontend:** Discover For You tab — "Why?" button per recommendation, modal with formatted explanation.

---

## Phase 2 — Smart Automation

### 2A. Smart Auto-Tagging
**Fill empty genre fields using AI + analysis data.**

**Backend:** `backend/services/ai/auto_tagger.py`
- `suggest_tags(track_ids, db)` — gather metadata + Essentia analysis + MusicBrainz data, batch 10 tracks per Claude call
- Returns: `[{"track_id": str, "suggested_genre": str, "confidence": float, "reasoning": str}]`
- `apply_tags(track_ids, db)` — writes to DB + audio files via mutagen

**API:** `POST /api/tracks/ai-tag` — `{"track_ids": list, "auto_apply": bool}`

**Frontend:** Library bulk actions — "AI Tag" button, confirmation modal with suggestions before applying.

**Schedule:** `ai_auto_tag` task (weekly, tags untagged tracks).

### 2B. Mood Tags
**Auto-label tracks with mood vocabulary.**

Moods: energetic, melancholic, upbeat, dark, chill, aggressive, dreamy, romantic, nostalgic, euphoric, ambient, intense, playful, mysterious, triumphant

**Backend:** `backend/services/ai/mood_tagger.py`
- Strategy 1 — CLAP-only (zero API cost): compute similarity between track audio embedding and text embeddings of mood words. Assign top 2-3 above threshold.
- Strategy 2 — AI-enhanced: combine CLAP scores with Essentia features, send to Claude for refinement.
- Config: `mood_strategy` in AssistantConfig ("clap_only" | "ai_enhanced", default "clap_only")

**Model:** `backend/models/mood.py` — `TrackMood` (track_id FK, mood, confidence, source, created_at)
**Migration:** new `track_moods` table

**API:** `POST /api/tracks/ai-moods`, `GET /api/tracks/moods`

**Frontend:** Library — mood filter pills, mood badges on tracks. Analysis page — "Generate Mood Tags" button.

### 2C. Listening Insights
**Weekly AI summary on Dashboard.**

**Backend:** `backend/services/ai/insights.py`
- `generate_insights(db)` — queries play_history (this week vs last), genre shifts, new additions, listening patterns
- Claude generates 3-5 brief insights: "You listened to 40% more electronic this week"
- Cached 24h in DB (TasteProfile.config JSON or separate table)

**API:** `GET /api/library/stats/insights`

**Frontend:** Dashboard — "Listening Insights" widget card. Stats page — expanded insights section.

---

## Phase 3 — Advanced Integration

### 3A. AI Duplicate Resolver
**Claude decides which duplicate to keep.**

**Backend:** `backend/services/ai/duplicate_resolver.py`
- `resolve_duplicates(group_ids, db)` — gather all track metadata + analysis + file info per group
- Claude: "Which track should be kept? Consider mastering quality, metadata completeness, naming conventions"
- Returns recommendations with reasoning (does NOT auto-delete)

**API:** `POST /api/library/duplicates/ai-resolve` — `{"group_keys": list}`

**Frontend:** Duplicates page — "AI Resolve" button, shows AI recommendations per group with reasoning.

### 3B. Download Quality Advisor
**AI picks best Soulseek source when results are ambiguous.**

**Backend:** `backend/services/ai/download_advisor.py`
- `rank_search_results(results, artist, track)` — analyzes filename patterns, format, reputation, file size
- Heuristic-first scoring (no Claude call for clear winners). Claude only for ambiguous cases (close scores, 5+ results).
- Adds `ai_score` and `ai_reasoning` to results

**Integration:** `backend/soulseek/search.py` — inject advisor scoring into result ranking

**Frontend:** Downloads page — "AI Pick" badge on recommended result with tooltip.

---

## Token Cost Estimates (per Claude call, Sonnet pricing)

| Feature | Input | Output | ~Cost/Call |
|---------|-------|--------|-----------|
| NL Search | ~800 | ~200 | $0.005 |
| AI Playlist | ~3000 | ~500 | $0.015 |
| Auto-Tag (10 tracks) | ~2000 | ~400 | $0.010 |
| Mood Tag (10 tracks) | ~2000 | ~300 | $0.010 |
| Insights | ~1500 | ~400 | $0.008 |
| Duplicate Resolve (5 groups) | ~2500 | ~500 | $0.012 |
| Download Advisor | ~1000 | ~200 | $0.005 |
| Why? Explanation | ~1200 | ~300 | $0.006 |

---

## Key Design Decisions

1. **CLAP-first for mood tags** — zero API cost primary strategy, Claude only for refinement
2. **NL Search detection** — heuristic avoids sending every search to Claude
3. **Batch Claude calls** — auto-tagging and mood tagging batch 10 tracks per call
4. **No auto-apply by default** — tag suggestions and duplicate resolutions presented for review
5. **Rate limiting** — global Semaphore(2) on Claude calls, insights cached 24h, search debounced 500ms
6. **Feature isolation** — each feature is a separate module, disabling one has zero impact on others
