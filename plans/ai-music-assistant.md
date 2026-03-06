# AI Music Assistant - Implementation Plan

## 1. Summary

A personalized recommendation engine that learns from listening behavior, favorites, audio analysis, and CLAP embeddings to suggest tracks for discovery and download. Hybrid architecture: daily rule-based scoring (free, local), on-demand Claude API (natural-language reasoning), and CLAP validation post-download.

Three new concepts:
- **Taste Profile**: Aggregated snapshot of user preferences (genre distribution, BPM ranges, energy, CLAP centroid)
- **Recommendations**: Scored candidate tracks from Last.fm with multi-signal ranking
- **Feedback Loop**: Thumbs up/down refines future scores

## 2. Architecture

```
Taste Profile Builder → Candidate Sourcing → Scoring Engine → Recommendations Table
        (daily)          (Last.fm APIs)     (multi-signal)        (sorted)
                                                                     |
        CLAP Validation ← Download Pipeline ←────────────────────────┘
        (post-download)                               |
                                                      v
                                               Claude API (on-demand)
                                               "Get AI Suggestions"
```

**Three tiers:**
1. **Rule-based (daily, free):** Taste profile → Last.fm candidates → weighted scoring
2. **Claude API (on-demand, paid):** Send profile + candidates for re-ranking with reasoning
3. **CLAP validation (post-download):** Compare embedding to taste centroid, flag mismatches

## 3. Taste Profile Builder

### Data Signals

| Signal | Source | Weight |
|--------|--------|--------|
| Genre distribution | Track.genre | High |
| Artist play counts | Track.play_count + Artist | High |
| Favorite artists | Favorite + Artist | High |
| BPM preference | TrackAnalysis.bpm | Medium |
| Energy preference | TrackAnalysis.energy | Medium |
| Danceability | TrackAnalysis.danceability | Medium |
| CLAP centroid | TrackEmbedding.embedding | High |
| Download history | Job type=download | Low |
| Blacklisted artists | DownloadBlacklist | Negative |
| Listening recency | Track.last_played_at | Medium |

### Computation

```python
async def build_taste_profile(db: AsyncSession) -> TasteProfile:
    # 1. Genre histogram (top 20 genres with percentages)
    # 2. Top artists by play_count (top 20)
    # 3. Favorited artist names
    # 4. Audio analysis stats (avg BPM, energy, danceability from played tracks)
    # 5. CLAP centroid (average embedding of favorites + most-played)
    # 6. Blacklisted artists
    return TasteProfile(...)
```

Stored as JSON blob in `taste_profiles` table, rebuilt daily. CLAP centroid stored as binary column.

## 4. Candidate Sourcing

Sources (in priority order):
1. **Similar tracks from favorites** -- `track.getSimilar` for top 20 favorites, 10 per = ~200 candidates
2. **Similar artists' top tracks** -- `artist.getSimilar` for top 10, `artist.getTopTracks` each = ~100 candidates
3. **Tag-based discovery** -- `tag.getTopTracks` for top 5 genres = ~250 candidates
4. **Trending overlap** -- `chart.getTopTracks` filtered to matching genres

### Dedup + Filtering
- Normalize artist+title (reuse `normalize_text`)
- Skip if already in library (exact match)
- Skip if blacklisted artist
- Skip if rejected in last 7 days
- Merge duplicates, keep highest source score

## 5. Scoring Engine

### Formula

```
score = (
    w_artist_affinity  * artist_affinity     +   # 0.25
    w_genre_match      * genre_match         +   # 0.20
    w_lastfm_similar   * lastfm_similarity   +   # 0.20
    w_audio_match      * audio_profile_match +   # 0.15
    w_clap_similarity  * clap_similarity     +   # 0.10
    w_popularity       * popularity          +   # 0.05
    w_novelty          * novelty_bonus           # 0.05
) * feedback_multiplier
```

### Signal Definitions

| Signal | Computation | Range |
|--------|-------------|-------|
| artist_affinity | 1.0 if favorited, 0.5-0.9 by similar match, 0.3 if in library | 0-1 |
| genre_match | Taste profile genre histogram lookup | 0-1 |
| lastfm_similar | Last.fm `match` float | 0-1 |
| audio_profile_match | Heuristic from Last.fm tags vs taste BPM/energy | 0-1 |
| clap_similarity | Cosine similarity to taste centroid (post-download only) | 0-1 |
| popularity | `min(1.0, listeners / 1_000_000)` | 0-1 |
| novelty_bonus | 1.0 if completely new artist, 0.5 if new track from known artist | 0-1 |
| feedback_multiplier | 1.0 default, 0.0 if rejected, 1.2 if similar liked | 0-1.5 |

Weights configurable in `[assistant]` config section.

## 6. Database Schema

### `recommendations` Table

```python
class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    track: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String)  # similar_track, similar_artist, tag, claude, trending
    source_detail: Mapped[str | None] = mapped_column(Text)  # JSON
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[str | None] = mapped_column(Text)  # JSON per-signal scores
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, accepted, rejected, downloaded, expired
    feedback: Mapped[str | None] = mapped_column(String)  # thumbs_up, thumbs_down
    explanation: Mapped[str | None] = mapped_column(Text)  # reason string
    lastfm_listeners: Mapped[int | None] = mapped_column(Integer)
    lastfm_match: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
```

### `taste_profiles` Table

```python
class TasteProfile(Base):
    __tablename__ = "taste_profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # "default"
    profile_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    clap_centroid: Mapped[bytes | None] = mapped_column(LargeBinary)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

## 7. API Contract

### `GET /api/recommendations`

```
Params: limit=25, offset=0, status=pending, source=null, min_score=0.0

Response:
{
  "items": [{
    "id": "uuid", "artist": "...", "track": "...",
    "source": "similar_track", "score": 0.85,
    "score_breakdown": {"artist_affinity": 0.9, ...},
    "explanation": "Similar to your favorite X by Y",
    "status": "pending", "feedback": null,
    "lastfm_listeners": 500000, "in_library": false
  }],
  "total": 150,
  "profile_computed_at": "...",
  "profile_stats": {"track_count": 1200, "top_genres": [...]}
}
```

### `POST /api/recommendations/refresh`

```
Body: {"force": false, "use_claude": false, "limit": 100}
Response: {"job_id": "uuid"}
```

### `POST /api/recommendations/feedback`

```
Body: {"recommendation_id": "uuid", "action": "thumbs_up|thumbs_down|download|dismiss"}
Response: {"ok": true}
```

### `GET /api/recommendations/profile`

Returns taste profile summary for UI display and Claude prompt.

## 8. Claude API Integration

### Config: `backend/config.py`

```python
class AssistantConfig(BaseModel):
    enabled: bool = False
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    max_suggestions_per_call: int = 20
    w_artist_affinity: float = 0.25
    w_genre_match: float = 0.20
    w_lastfm_similar: float = 0.20
    w_audio_match: float = 0.15
    w_clap_similarity: float = 0.10
    w_popularity: float = 0.05
    w_novelty: float = 0.05
```

### Prompt Template

```
Music taste profile:
- Top genres: {genre distribution}
- Top artists: {by play count}
- BPM: {mean} +/- {stddev}
- Energy: {mean}, Danceability: {mean}

Current candidates (pre-scored):
{candidates JSON}

Instructions:
1. Re-rank top 20 by taste fit
2. 1-sentence explanation per pick
3. Suggest 5 additional tracks not in candidates
4. Flag poor fits

Return JSON: {ranked, additional, flagged}
```

### Rate Limiting & Cost

- On-demand only (never auto-scheduled)
- Cache results 24 hours
- Show estimated cost in UI (~$0.01-0.03 per call with Sonnet)
- `assistant.enabled = false` hides "Get AI Suggestions" button

## 9. Frontend -- "For You" Tab on Discover Page

Add fifth tab to existing Discover page:

```javascript
{ key: 'foryou', label: 'For You', icon: Sparkles }
```

### Layout

```
+--------------------------------------------------+
| For You                              [Refresh] [AI]|
+--------------------------------------------------+
| Taste Profile Summary Card                         |
| Genres: electronic 35%, ambient 22% | BPM: 128 avg|
+--------------------------------------------------+
| Recommendations (sorted by score)                  |
| Score | Track | Artist | Why              | Actions|
| 0.92  | A     | X      | Similar to...   | DL ↑ ↓ |
+--------------------------------------------------+
| ScheduleControl: Daily Recommendations             |
+--------------------------------------------------+
```

### Components

- Score badge: color gradient red→yellow→green
- Explanation: expandable per-signal breakdown on click
- Feedback: thumbs up/down buttons per row
- Download: same pattern as existing Discover inline download
- AI button: "Get AI Suggestions", disabled without API key, loading spinner
- Profile card: compact collapsible taste summary

## 10. Scheduled Task

### Registration in `backend/api/schedule.py`

```python
{"task_name": "recommendation_refresh", "interval_hours": 24, "run_at": "05:30"},
"recommendation_refresh": "AI Recommendations",
"recommendation_refresh": "Rebuild taste profile and generate fresh recommendations.",
```

### Task Flow

1. Build/update taste profile
2. Source candidates from Last.fm
3. Deduplicate + filter (library, blacklist, recent rejections)
4. Score using weighted formula
5. Store top 100 in `recommendations` table
6. Expire old (>7 days pending)
7. Broadcast completion via WebSocket

## 11. Implementation Steps

### Phase 1: Base Scoring (2-3 sessions)

**Create:**
1. `backend/models/recommendation.py`
2. `backend/models/taste_profile.py`
3. `backend/services/recommender.py` (profile builder, sourcer, scorer)
4. `backend/api/recommendations.py`

**Modify:**
5. `backend/models/__init__.py` -- register models
6. `backend/config.py` -- add AssistantConfig
7. `backend/main.py` -- register router
8. `backend/api/schedule.py` -- add task
9. `backend/workers/scheduler.py` -- add dispatch
10. Alembic migration

### Phase 2: Frontend (1-2 sessions)
11. Add "For You" tab to `discover/+page.svelte`
12. Add API methods to `api.js`
13. Profile card, recommendation list, feedback buttons, download integration

### Phase 3: Claude Integration (1 session)
14. Create `backend/services/claude.py`
15. Add `use_claude` to recommender
16. Add "Get AI Suggestions" button to frontend
17. Add Claude API key field to Settings

### Phase 4: Feedback Loop (1 session)
18. Feedback-weighted scoring adjustments
19. CLAP validation post-download
20. Score breakdown tooltip in UI

## 12. Edge Cases

| Case | Handling |
|------|----------|
| Empty library (<10 tracks) | Show "Add more music" empty state |
| No favorites | Fall back to play_count + genre only |
| No analysis data | Skip audio_match signal, redistribute weight |
| No Last.fm API key | Show warning; profile works but no candidates |
| CLAP centroid <5 embeddings | Set clap_similarity weight to 0 |
| Last.fm rate limiting | 15-30 calls per refresh, within limits |
| SQLite single-writer | Batch writes in single session, commits every 10 |
| Stale recommendations | Auto-expire after 7 days |
| Claude API failure | Graceful degradation; keep rule-based scores; show toast |
| Blacklist after recommendation | Mark recommendations as expired |

## 13. Testing Checklist

### Backend
- [ ] Taste profile builds with all fields
- [ ] Handles empty library, no favorites, no analysis
- [ ] Candidate sourcing deduplicates correctly
- [ ] Filters blacklisted + in-library
- [ ] Scoring produces 0-1 range
- [ ] Weight redistribution when CLAP missing
- [ ] Feedback multiplier adjusts correctly
- [ ] Expiry removes old pending entries
- [ ] Claude prompt renders valid JSON
- [ ] Claude response parser handles code blocks + malformed

### API
- [ ] GET /api/recommendations paginated with correct total
- [ ] Status filter works
- [ ] POST /refresh creates job with job_id
- [ ] POST /feedback updates status
- [ ] GET /profile returns valid data

### Frontend
- [ ] "For You" tab loads recommendations
- [ ] Profile card renders
- [ ] Score badges correct colors
- [ ] Download button works
- [ ] Thumbs up/down update status
- [ ] "Get AI Suggestions" hidden when disabled
- [ ] Empty state when no recommendations
- [ ] ScheduleControl works

### End-to-End
- [ ] Full cycle: profile → source → score → display
- [ ] Download recommendation → appears in library
- [ ] Reject → doesn't reappear next refresh
- [ ] Claude re-ranking integrates smoothly
- [ ] Scheduled task runs and produces recommendations
