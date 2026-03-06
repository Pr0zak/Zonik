# Christmas Auto-Playlist - Implementation Plan

## 1. Summary

Add a "Christmas" seasonal playlist that detects holiday tracks in the library by keyword matching on title, album, and genre fields. Rebuilt on demand via manual trigger (not auto-scheduled). A toggle controls visibility to Subsonic clients (Symfonium) -- when disabled, the playlist is hidden from `getPlaylists` response but remains in the database. Adds `is_seasonal` boolean to `playlists` table, a new scheduled task handler, and minimal frontend changes on the Playlists page.

## 2. Keyword Detection

### Comprehensive Word List (case-insensitive, partial match via ILIKE)

```python
CHRISTMAS_KEYWORDS = [
    # Core
    "christmas", "xmas", "x-mas",
    # Religious
    "noel", "nativity", "bethlehem", "manger", "holy night",
    # Songs/themes
    "jingle bell", "silent night", "deck the hall", "rudolph",
    "frosty the snowman", "winter wonderland", "let it snow",
    "white christmas", "little drummer boy", "feliz navidad",
    "auld lang syne", "carol of the bell", "o holy night",
    "away in a manger", "o come all ye faithful", "hark the herald",
    "twelve days of christmas", "twelve days of xmas",
    "santa claus", "santa baby", "st. nicholas",
    "sleigh ride", "nutcracker", "chestnuts roasting",
    "have yourself a merry", "rockin around the",
    "last christmas", "all i want for christmas",
    "do they know it", "wonderful christmastime",
    "blue christmas", "holly jolly",
    # Genre tags
    "holiday", "christmas music",
]
```

### Matching Strategy

- Check `Track.title`, `Track.genre`, and joined `Album.title` against each keyword using `or_` with `ilike(f"%{kw}%")`
- Deduplicate results (track matching multiple keywords appears once)
- File path NOT checked (too noisy)
- Order by artist then title for pleasant playlist ordering

## 3. Database Changes

### Add `is_seasonal` to Playlists

**Alembic Migration:**
```python
def upgrade():
    op.add_column('playlists', sa.Column('is_seasonal', sa.Boolean(), nullable=True, server_default=sa.false()))

def downgrade():
    op.drop_column('playlists', 'is_seasonal')
```

**Model change in `backend/models/playlist.py`:**
```python
is_seasonal: Mapped[bool] = mapped_column(Boolean, default=False)
```

This generalizes to future seasonal playlists (Halloween, etc.) using the same mechanism.

## 4. Scheduled Task

### Handler in `backend/workers/scheduler.py`

```python
async def _run_christmas_playlist(db: AsyncSession):
    from sqlalchemy import delete, or_
    from backend.models.album import Album

    existing = (await db.execute(
        select(Playlist).where(Playlist.name == "Christmas")
    )).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))

    conditions = []
    for kw in CHRISTMAS_KEYWORDS:
        pat = f"%{kw}%"
        conditions.append(Track.title.ilike(pat))
        conditions.append(Track.genre.ilike(pat))
        conditions.append(Album.title.ilike(pat))

    query = (
        select(Track)
        .outerjoin(Album, Track.album_id == Album.id)
        .where(or_(*conditions))
        .order_by(Track.title)
    )
    tracks = (await db.execute(query)).scalars().unique().all()

    if not tracks:
        return

    playlist = Playlist(
        id=str(uuid.uuid4()), name="Christmas", is_public=True,
        is_seasonal=True, comment=f"Auto-generated: {len(tracks)} holiday tracks",
    )
    db.add(playlist)
    await db.flush()
    for i, t in enumerate(tracks):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=t.id, position=i))
    await db.commit()
```

Wire into `run_task()`:
```python
elif task_name == "playlist_christmas":
    await _run_christmas_playlist(db)
```

### Registration in `backend/api/schedule.py`

```python
# DEFAULT_TASKS:
{"task_name": "playlist_christmas", "interval_hours": 0, "run_at": None, "enabled": False},

# TASK_LABELS:
"playlist_christmas": "Christmas Playlist",

# TASK_DESCRIPTIONS:
"playlist_christmas": "Rebuild the Christmas playlist from holiday-tagged tracks. Manual trigger only.",
```

`interval_hours: 0` + `enabled: False` ensures manual-only trigger.

## 5. Config Toggle -- Season Active

Use existing `ScheduleTask.config` JSON field (same pattern as `auto_download`, `auto_after_scan`):

```json
{"season_active": true}
```

### New API Endpoints in `backend/api/playlists.py`

```python
@router.post("/christmas/toggle")
async def toggle_christmas_season(db: AsyncSession = Depends(get_db)):
    task = (await db.execute(
        select(ScheduleTask).where(ScheduleTask.task_name == "playlist_christmas")
    )).scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Christmas task not configured")
    config = json.loads(task.config) if task.config else {}
    config["season_active"] = not config.get("season_active", False)
    task.config = json.dumps(config)
    await db.commit()
    return {"season_active": config["season_active"]}

@router.get("/christmas/status")
async def christmas_status(db: AsyncSession = Depends(get_db)):
    task = (await db.execute(
        select(ScheduleTask).where(ScheduleTask.task_name == "playlist_christmas")
    )).scalar_one_or_none()
    config = json.loads(task.config) if task and task.config else {}
    playlist = (await db.execute(
        select(Playlist).where(Playlist.name == "Christmas", Playlist.is_seasonal == True)
    )).scalar_one_or_none()
    return {
        "exists": playlist is not None,
        "track_count": 0,  # count from playlist_tracks if exists
        "season_active": config.get("season_active", False),
        "last_run_at": task.last_run_at.isoformat() if task and task.last_run_at else None,
    }
```

## 6. Subsonic Filtering

### Modify `backend/subsonic/playlists_api.py` `get_playlists`

After loading playlists, filter out seasonal playlists whose season is not active:

```python
# Load seasonal task configs
seasonal_tasks = (await db.execute(
    select(ScheduleTask).where(ScheduleTask.task_name.like("playlist_%"))
)).scalars().all()
seasonal_active = set()
for t in seasonal_tasks:
    cfg = json.loads(t.config) if t.config else {}
    if cfg.get("season_active"):
        seasonal_active.add(t.task_name)

# Filter playlists
filtered = []
for p in playlists:
    if p.is_seasonal:
        task_name = f"playlist_{p.name.lower()}"
        if task_name not in seasonal_active:
            continue
    filtered.append(p)
```

- Only affects Subsonic clients (Symfonium)
- Web UI always shows the playlist with season status indicator
- Direct `getPlaylist?id=<id>` still works (access by ID is always allowed)

## 7. Frontend Changes

### Playlists Page: `frontend/src/routes/playlists/+page.svelte`

Add Christmas section card below existing schedule controls:

```svelte
{#if christmasStatus}
  <Card padding="p-4" class="mt-6">
    <div class="flex items-center gap-2 mb-3">
      <Snowflake class="w-4 h-4 text-cyan-400" />
      <span class="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">Seasonal Playlist</span>
    </div>
    <div class="flex items-center justify-between">
      <div>
        <h4 class="text-sm font-medium">Christmas Playlist</h4>
        <p class="text-xs text-[var(--text-muted)]">
          {christmasStatus.exists ? `${christmasStatus.track_count} holiday tracks` : 'Not yet generated'}
        </p>
      </div>
      <div class="flex items-center gap-3">
        <!-- Season toggle (Visible / Hidden) -->
        <label class="flex items-center gap-2 cursor-pointer">
          <span class="text-xs text-[var(--text-muted)]">
            {christmasStatus.season_active ? 'Visible' : 'Hidden'}
          </span>
          <!-- toggle switch button -->
        </label>
        <!-- Rebuild button -->
        <Button variant="secondary" size="sm" onclick={rebuildChristmas}>
          <RefreshCw class="w-3.5 h-3.5" />
          {christmasStatus.exists ? 'Rebuild' : 'Generate'}
        </Button>
      </div>
    </div>
  </Card>
{/if}
```

Show snowflake icon on seasonal playlist cards in the grid view. Import `Snowflake, RefreshCw` from lucide-svelte.

### Schedule Page

Add `playlist_christmas` to Playlists task group.

### Playlist API Response

Include `is_seasonal` in `list_playlists` response so frontend can show snowflake badge.

## 8. Implementation Steps

1. **Migration** -- add `is_seasonal` boolean to playlists table
2. **Model** -- add `is_seasonal` to Playlist model
3. **Scheduler** -- add `CHRISTMAS_KEYWORDS` + `_run_christmas_playlist()` + dispatch
4. **Schedule defaults** -- register `playlist_christmas` task
5. **Playlist API** -- add `/christmas/toggle` and `/christmas/status` endpoints; include `is_seasonal` in list response
6. **Subsonic filter** -- modify `get_playlists` to exclude inactive seasonal playlists
7. **Frontend playlists** -- Christmas card with toggle + rebuild
8. **Frontend schedule** -- add to Playlists task group
9. **Migration on production** -- `/ct-migrate`

## 9. Edge Cases

| Case | Handling |
|------|----------|
| No Christmas tracks found | Handler returns without creating playlist; UI shows "Not yet generated" |
| Tracks added after scan | User clicks "Rebuild" to re-scan; deletes old playlist, creates new one |
| Multiple seasonal playlists | `is_seasonal` + `season_active` pattern generalizes (Halloween, etc.) |
| Toggle when no playlist exists | Toggle only changes config flag; Subsonic filter has nothing to hide |
| Keyword false positives | "Holiday" might match non-Christmas tracks; acceptable -- user can manually edit |
| Subsonic client caches | Takes effect on next `getPlaylists` call (next sync) |
| Playlist deleted manually | Rebuild recreates it with `is_seasonal=True` |
| NULL genre/album | `outerjoin` on Album ensures title/genre still checked; NULL ILIKE is falsy |

## 10. Testing Checklist

- [ ] Migration applies cleanly
- [ ] Backend loads after model change
- [ ] `POST /api/schedule/playlist_christmas/run` creates Christmas playlist with matching tracks
- [ ] `GET /api/playlists/christmas/status` returns correct exists/count/season_active
- [ ] `POST /api/playlists/christmas/toggle` flips season_active
- [ ] Subsonic `getPlaylists` includes Christmas when season_active=true
- [ ] Subsonic `getPlaylists` excludes Christmas when season_active=false
- [ ] Direct `getPlaylist?id=<id>` still works regardless of season
- [ ] Frontend shows Christmas card with correct status
- [ ] Toggle switch updates and reflects visually
- [ ] Rebuild button triggers task and refreshes
- [ ] Snowflake icon on seasonal playlist cards
- [ ] Schedule page shows task in Playlists group
- [ ] Empty library -- generate completes without error
- [ ] Rebuild picks up newly added Christmas tracks
