# User Ratings (Symfonium Star Ratings) - Implementation Plan

## 1. Summary

Symfonium sends `setRating?id=xxx&rating=3` when a user rates a track. Currently, the `setRating` endpoint in `backend/subsonic/annotation.py` (line 151-155) is a no-op. This plan adds full rating persistence, Subsonic response integration (`userRating` field), a REST API for the web UI, and a star-rating component in the library frontend.

Ratings follow the Subsonic spec: integer 1-5 (stars), with 0 meaning "remove rating." Single-user app, so ratings are stored directly on the Track model.

## 2. Database Changes

### Model Change: `backend/models/track.py`

Add a single column to the `Track` model after `play_count`:

```python
rating: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
```

### Alembic Migration

```python
def upgrade() -> None:
    op.add_column('tracks', sa.Column('rating', sa.Integer(), nullable=True))

def downgrade() -> None:
    op.drop_column('tracks', 'rating')
```

## 3. Backend Changes

### 3.1 Subsonic `setRating`: `backend/subsonic/annotation.py`

Replace the current no-op (lines 151-155) with actual persistence:

```python
@router.get("/setRating")
@router.get("/setRating.view")
@router.post("/setRating")
@router.post("/setRating.view")
async def set_rating(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    song_id = params.get("id")
    rating_str = params.get("rating", "0")

    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    try:
        rating = int(rating_str)
    except (ValueError, TypeError):
        return error_response(0, "Invalid rating value", _get_format(request))

    if rating < 0 or rating > 5:
        return error_response(0, "Rating must be between 0 and 5", _get_format(request))

    result = await db.execute(select(Track).where(Track.id == song_id))
    track = result.scalar_one_or_none()
    if not track:
        return error_response(70, "Song not found", _get_format(request))

    track.rating = rating if rating > 0 else None
    await db.commit()

    return subsonic_response({}, _get_format(request))
```

### 3.2 Subsonic responses: `backend/subsonic/responses.py`

**In `format_track()`:** Add after the `playCount` line:

```python
"userRating": track.rating,
```

Since `None` values are already filtered out (`{k: v for k, v in data.items() if v is not None}`), this only appears when a track has been rated.

**In `format_album()`:** Add `averageRating` when tracks are provided:

```python
rated = [t.rating for t in tracks if t.rating]
if rated:
    data["averageRating"] = round(sum(rated) / len(rated), 1)
```

### 3.3 REST API: `backend/api/tracks.py`

**Add `rating` to track list/detail responses** after `play_count`:

```python
"rating": t.rating,
```

**Add new rating endpoint:**

```python
class RatingRequest(BaseModel):
    rating: int  # 0-5, 0 = unrate

@router.put("/{track_id}/rating")
async def set_rating(track_id: str, req: RatingRequest, db: AsyncSession = Depends(get_db)):
    if req.rating < 0 or req.rating > 5:
        raise HTTPException(400, "Rating must be between 0 and 5")

    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    track.rating = req.rating if req.rating > 0 else None
    await db.commit()
    return {"ok": True, "rating": track.rating}
```

**Add rating sort** (NULLs last):

```python
elif sort == "rating":
    from sqlalchemy import case
    rating_order = case((Track.rating.is_(None), 0), else_=Track.rating)
    if order == "desc":
        query = query.order_by(rating_order.desc(), Track.title.asc())
    else:
        query = query.order_by(rating_order.asc(), Track.title.asc())
```

**Add `min_rating` filter parameter:**

```python
min_rating: int | None = None,
```

```python
if min_rating is not None:
    query = query.where(Track.rating >= min_rating)
```

### 3.4 Subsonic `getAlbumList2` "highest" type: `backend/subsonic/lists.py`

Add `highest` type (highest-rated albums by average track rating):

```python
elif list_type == "highest":
    avg_rating = func.avg(Track.rating).label("avg_rating")
    query = (
        select(Album).options(selectinload(Album.artist))
        .join(Track, Track.album_id == Album.id)
        .where(Track.rating.isnot(None))
        .group_by(Album.id)
        .order_by(avg_rating.desc())
    )
```

## 4. Subsonic Response Changes -- Full Audit

Every call site of `format_track()` automatically picks up `userRating`:

| File | Endpoint | Notes |
|------|----------|-------|
| `responses.py` | `format_track()` | Central -- add `userRating` here |
| `browsing.py` | `getMusicDirectory`, `getSong`, `getSimilarSongs2`, `getTopSongs` | Auto via `format_track` |
| `search.py` | `search3` | Auto via `format_track` |
| `lists.py` | `getRandomSongs`, `getSongsByGenre`, `getStarred2` | Auto via `format_track` |
| `playlists_api.py` | `getPlaylist` | Auto via `format_track` |
| `bookmarks.py` | `getBookmarks`, `getPlayQueue` | Auto via `format_track` |

No changes needed in these files -- they all delegate to `format_track()`.

## 5. API Contract

### Subsonic API

**`setRating`** (GET/POST)
- Params: `id` (track ID), `rating` (0-5)
- Rating 0 = clear/unrate
- Response: empty Subsonic OK

**Song responses** gain `userRating` field (integer 1-5, omitted when not rated).

### REST API

**`PUT /api/tracks/{track_id}/rating`**
- Body: `{"rating": 3}` (0 = unrate, 1-5 = set)
- Response: `{"ok": true, "rating": 3}`

**`GET /api/tracks`** gains:
- Response: each track includes `"rating": <int|null>`
- Query param: `min_rating=3` (optional filter)
- Sort: `sort=rating` (NULLs sort last)

## 6. Frontend Changes

### 6.1 New Component: `frontend/src/components/ui/StarRating.svelte`

5 clickable star icons (lucide `Star`). Filled/gold for rated stars, outline/dim for unrated. Click same star again to unrate.

```svelte
<script>
  import { Star } from 'lucide-svelte';

  let { rating = null, size = 'sm', onrate = () => {} } = $props();
  let hover = $state(0);

  function handleClick(value, e) {
    e.stopPropagation();
    const newRating = value === rating ? 0 : value;
    onrate(newRating);
  }
</script>

<div class="flex items-center gap-0.5"
  onmouseleave={() => hover = 0}>
  {#each [1,2,3,4,5] as star}
    <button
      class="p-0 transition-colors"
      onmouseenter={() => hover = star}
      onclick={(e) => handleClick(star, e)}
    >
      <Star class="{size === 'xs' ? 'w-3 h-3' : 'w-3.5 h-3.5'}
        {(hover ? star <= hover : star <= (rating || 0))
          ? 'text-amber-400'
          : 'text-[var(--text-disabled)]'}"
        fill={(hover ? star <= hover : star <= (rating || 0)) ? 'currentColor' : 'none'} />
    </button>
  {/each}
</div>
```

### 6.2 API Client: `frontend/src/lib/api.js`

```javascript
setRating: (id, rating) => request(`/tracks/${id}/rating`, {
  method: 'PUT',
  body: JSON.stringify({ rating })
}),
```

### 6.3 Library Page: `frontend/src/routes/library/+page.svelte`

**Rating handler:**
```javascript
async function setTrackRating(trackId, rating) {
  try {
    await api.setRating(trackId, rating);
    const idx = tracks.findIndex(t => t.id === trackId);
    if (idx >= 0) tracks[idx] = { ...tracks[idx], rating: rating || null };
  } catch (e) {
    addToast('Rating failed', 'error');
  }
}
```

**List view:** Add "Rating" column header (sortable) and `<StarRating>` cell in each row.

**Grid view:** Show star badge on rated tracks: `<Star class="w-3 h-3" fill="currentColor" />{track.rating}`

**Context menu:** Add inline `<StarRating>` in the track action menu.

**Rating filter:** Dropdown select for minimum rating (1-5 stars) alongside existing analyzed filter.

## 7. Implementation Steps

1. Add `rating` column to Track model (`backend/models/track.py`)
2. Create Alembic migration
3. Implement `setRating` endpoint (`backend/subsonic/annotation.py`) -- enables Symfonium immediately
4. Add `userRating` to `format_track()` (`backend/subsonic/responses.py`)
5. Add `averageRating` to `format_album()` (`backend/subsonic/responses.py`)
6. Add `highest` type to `getAlbumList2` (`backend/subsonic/lists.py`)
7. Add rating to REST API responses + new PUT endpoint + sort/filter (`backend/api/tracks.py`)
8. Add `setRating` to API client (`frontend/src/lib/api.js`)
9. Create `StarRating.svelte` component (`frontend/src/components/ui/StarRating.svelte`)
10. Integrate into library page -- list view column, grid badge, context menu, filter
11. Run migration on production (`/ct-migrate`)
12. Test with Symfonium

## 8. Edge Cases

| Case | Behavior |
|------|----------|
| `rating=0` | Clears rating (`track.rating = None`), `userRating` omitted from responses |
| `rating > 5` or `rating < 0` | Return Subsonic error / HTTP 400 |
| Non-integer rating | Return error (Subsonic spec is integer only) |
| Album/artist ID passed to `setRating` | Return error 70 (not found). No album/artist ratings needed. |
| Track deleted after rating | Rating is on Track row, deleted with the track |
| Sorting by rating with many unrated | NULLs sort last via `CASE` expression |
| Library scan re-import | Track IDs stable (MD5 of file path), ratings survive re-scans |
| `format_track` without `rating` loaded | Column on Track directly, always loaded (no `selectinload` needed) |

## 9. Testing Checklist

- [ ] Migration applies: `uv run alembic upgrade head`
- [ ] Subsonic setRating: `GET /rest/setRating?id=<id>&rating=3` returns OK
- [ ] Subsonic setRating(0): clears rating
- [ ] Subsonic setRating validation: rating=6 returns error, missing id returns error
- [ ] Subsonic getSong: rated track includes `userRating: 3`
- [ ] Subsonic getSong (unrated): response does NOT include `userRating`
- [ ] Subsonic search3: rated tracks include `userRating`
- [ ] Subsonic getAlbumList2 type=highest: returns albums by average track rating
- [ ] REST API GET /api/tracks: includes `rating` field
- [ ] REST API PUT /api/tracks/{id}/rating: setting 1-5 works, 0 clears
- [ ] REST API sort=rating: NULLs last
- [ ] REST API min_rating=3: only returns rated tracks
- [ ] Frontend list view: star rating column renders, clicking sets rating
- [ ] Frontend grid view: rated tracks show star badge
- [ ] Frontend context menu: rating stars work
- [ ] Frontend rating filter: dropdown filters correctly
- [ ] Symfonium: rate a track, verify rating persists on next sync
- [ ] Downgrade migration: `uv run alembic downgrade -1` drops column cleanly
