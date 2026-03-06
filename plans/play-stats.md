# Play Stats & Listening History Charts - Implementation Plan

## 1. Summary

Add a `play_history` table to record timestamped play events (from both Subsonic scrobble and web UI play endpoints), a new API endpoint to serve aggregated listening history data, and Chart.js charts on the Stats page showing plays over time, top tracks/artists by period, and listening patterns by hour-of-day. This follows the exact same architecture as the existing Soulseek stats history feature (model in `backend/models/stats.py`, Chart.js pattern from `frontend/src/routes/stats/+page.svelte`).

## 2. Database Schema

### New Model: `backend/models/play_history.py`

```python
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base

class PlayHistory(Base):
    __tablename__ = "play_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True)
    played_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, default="web")  # "subsonic" or "web"
```

Indexes: `track_id` (for per-track lookups), `played_at` (for time-range queries). No relationship back to Track needed (lightweight event log).

### Alembic Migration

```bash
uv run alembic revision --autogenerate -m "add play_history table"
```

Creates `play_history` table with columns: `id` (Integer PK autoincrement), `track_id` (String FK to tracks.id ON DELETE CASCADE), `played_at` (DateTime NOT NULL), `source` (String). Creates indexes on `track_id` and `played_at`. Downgrade drops both indexes then the table.

## 3. Backend Changes

### 3a. Register model in `backend/models/__init__.py`

Add `from backend.models.play_history import PlayHistory` and add `"PlayHistory"` to the `__all__` list.

### 3b. Record play events in `backend/subsonic/annotation.py` (scrobble endpoint)

Inside the `if submission == "true":` block, after updating `track.play_count` and `track.last_played_at`, add:

```python
from backend.models.play_history import PlayHistory
db.add(PlayHistory(track_id=song_id, played_at=datetime.utcnow(), source="subsonic"))
```

Piggybacks on the existing commit in the same transaction.

### 3c. Record play events in `backend/api/tracks.py` (record_play endpoint)

Inside the `record_play` function, after updating `track.play_count` and `track.last_played_at`, before `await db.commit()`, add:

```python
from backend.models.play_history import PlayHistory
db.add(PlayHistory(track_id=track_id, played_at=datetime.utcnow(), source="web"))
```

### 3d. New API endpoint in `backend/api/library.py`

Add `GET /api/library/stats/play-history` alongside the existing `/api/library/stats/detailed` endpoint.

```python
@router.get("/stats/play-history")
async def play_history_stats(
    hours: int = 168,  # default 7 days
    db: AsyncSession = Depends(get_db),
):
```

**Aggregation queries:**

- `plays_over_time`: Group by hour (using `func.strftime('%Y-%m-%dT%H:00:00', PlayHistory.played_at)`) for ranges <= 72h, by day for ranges > 72h
- `top_tracks`: Join Track + Artist tables, GROUP BY track_id, ORDER BY count DESC, LIMIT 10
- `top_artists`: Join Track + Artist, GROUP BY artist_id, ORDER BY count DESC, LIMIT 10
- `by_hour`: `func.strftime('%H', PlayHistory.played_at)` cast to int, GROUP BY hour, produces 0-23 buckets
- All queries filtered by `PlayHistory.played_at >= cutoff` where `cutoff = datetime.utcnow() - timedelta(hours=hours)`

## 4. API Contract

### `GET /api/library/stats/play-history?hours=168`

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| hours | int | 168 | Lookback window in hours |

**Response (200):**
```json
{
  "plays_over_time": [
    {"timestamp": "2026-03-06T14:00:00", "count": 5}
  ],
  "top_tracks": [
    {"title": "Song Name", "artist": "Artist Name", "track_id": "abc123", "count": 12}
  ],
  "top_artists": [
    {"name": "Artist Name", "count": 25}
  ],
  "by_hour": [
    {"hour": 0, "count": 3}
  ],
  "total_plays": 142,
  "period_hours": 168
}
```

## 5. Frontend Changes

### File: `frontend/src/routes/stats/+page.svelte`

Add a new "Listening History" section with:

#### State variables
```javascript
let playHistory = $state(null);
let playHours = $state(168);
let playsChartEl = $state(null);
let hourChartEl = $state(null);
let playsChart = null;
let hourChart = null;
```

#### Data fetching
Add `loadPlayHistory()` function (same pattern as `loadHistory()` for Soulseek charts):

```javascript
async function loadPlayHistory() {
    playHistory = await fetch(`/api/library/stats/play-history?hours=${playHours}`).then(r => r.json());
    await new Promise(r => setTimeout(r, 0));
    buildPlayCharts();
}
```

#### Charts

1. **Plays Over Time** (line chart) -- cyan color (`#06b6d4`), same style as Soulseek peers chart
   - X axis: timestamps from `plays_over_time`
   - Y axis: play counts
   - `fill: true`, `tension: 0.3`, `pointRadius: 0`, `borderWidth: 1.5`

2. **Listening by Hour** (bar chart) -- indigo color (`#6366f1`), 24 bars for hours 0-23
   - X axis: hour labels (12am, 1am, ... 11pm)
   - Y axis: play counts

#### UI section

```svelte
{#if playHistory && playHistory.total_plays > 0}
    <Card padding="p-4" class="mb-8">
        <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-2">
                <TrendingUp class="w-4 h-4 text-[var(--color-stats)]" />
                <h2 class="text-xs font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    Listening History
                </h2>
                <span class="text-xs text-[var(--text-muted)]">
                    {playHistory.total_plays} plays
                </span>
            </div>
            <!-- Time range selector: 24h / 7d / 30d / 90d -->
            <div class="flex gap-1">...</div>
        </div>

        <!-- 2-column chart grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <!-- Plays Over Time (line) -->
            <!-- Listening by Hour (bar) -->
        </div>

        <!-- Top Tracks & Top Artists (side by side lists) -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">...</div>
    </Card>
{/if}
```

Top tracks/artists lists use horizontal bar layout matching existing "Top Artists" and "Top Genres" sections.

#### Cleanup
Add `playsChart` and `hourChart` to the `destroyCharts()` function.

## 6. Implementation Steps

1. Create `backend/models/play_history.py` -- the PlayHistory model
2. Update `backend/models/__init__.py` -- import and register PlayHistory
3. Create Alembic migration -- `uv run alembic revision --autogenerate -m "add play_history table"`
4. Modify `backend/subsonic/annotation.py` -- add PlayHistory insert in scrobble endpoint
5. Modify `backend/api/tracks.py` -- add PlayHistory insert in record_play endpoint
6. Add `GET /api/library/stats/play-history` endpoint in `backend/api/library.py`
7. Verify backend loads -- `uv run python -c "from backend.main import app; print('OK')"`
8. Run migration on production -- `/ct-migrate`
9. Update `frontend/src/routes/stats/+page.svelte` -- add state, fetch, chart builders, and UI
10. Test frontend build -- `cd frontend && npm run build`
11. Deploy -- push + upgrade CT 228

Steps 1-3 sequential (model before migration). Steps 4-6 independent but depend on step 1. Step 9 depends on step 6 (needs API).

## 7. Edge Cases and Considerations

- **No play history yet**: Section gated on `playHistory.total_plays > 0`; won't render empty charts
- **SQLite single-writer**: PlayHistory INSERT in same transaction as existing play_count update
- **CASCADE delete**: Track deletion auto-removes play_history rows
- **Subsonic now playing vs submission**: Only `submission == "true"` creates records (existing check)
- **Timezone**: All timestamps use `datetime.utcnow()` (consistent with codebase); frontend formats locally
- **Large datasets**: `played_at` index makes time-range queries efficient; grouping by day keeps response small (~90 points max for 90d)
- **Duplicate plays**: Symfonium may send scrobble multiple times; records every event (mirrors real behavior)
- **Data retention**: No automatic pruning; play history is valuable long-term data
- **`by_hour` aggregation**: SQLite `strftime('%H', played_at)` returns '00'-'23'; backend fills missing hours with 0

## 8. Testing Checklist

- [ ] Migration applies cleanly: `uv run alembic upgrade head`
- [ ] Migration rolls back cleanly: `uv run alembic downgrade -1`
- [ ] Backend loads: `uv run python -c "from backend.main import app; print('OK')"`
- [ ] Subsonic scrobble creates PlayHistory row
- [ ] Web play creates PlayHistory row
- [ ] Play history API returns data: `GET /api/library/stats/play-history?hours=24`
- [ ] Play history API returns empty gracefully (total_plays = 0)
- [ ] Frontend builds: `cd frontend && npm run build`
- [ ] Charts render with data (visual check)
- [ ] Time range selector changes chart data (24h/7d/30d/90d)
- [ ] Track deletion cascades to play_history
- [ ] `by_hour` returns all 24 hours (0-23) even if some have 0 plays
- [ ] Top tracks/artists show correct ranking for selected period
- [ ] No regression on existing Stats page sections
