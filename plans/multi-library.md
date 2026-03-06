# Multi-Library System - Implementation Plan

## 1. Summary

Introduces toggleable music collections (e.g., "Main", "Christmas", "Techno/Dance") to Zonik. Each track belongs to exactly one library. Libraries can be enabled or disabled. When disabled, tracks are invisible to Symfonium and all Subsonic clients -- they vanish from browsing, search, playlists, and every other endpoint.

Maps directly onto the Subsonic `getMusicFolders` / `musicFolderId` parameter convention so Symfonium's built-in music folder selector works out of the box.

Key principles:
- Every track belongs to exactly one `MusicLibrary` (default: "Main", ID 1)
- Libraries have detection rules (genre keywords, directory prefixes) evaluated during scan
- Global `enabled` flag controls visibility
- Single shared helper applies library filter to all SQLAlchemy queries
- Backward-compatible: existing tracks get `library_id = 1`

## 2. Database Schema

### New Table: `music_libraries`

```python
# backend/models/music_library.py
class MusicLibrary(Base):
    __tablename__ = "music_libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    color: Mapped[str | None] = mapped_column(String)        # hex color for UI
    icon: Mapped[str | None] = mapped_column(String)          # lucide icon name
    detection_rules: Mapped[str | None] = mapped_column(Text) # JSON rules
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tracks: Mapped[list["Track"]] = relationship("Track", back_populates="library")
```

### Add `library_id` to Track

```python
# backend/models/track.py
library_id: Mapped[int | None] = mapped_column(
    Integer, ForeignKey("music_libraries.id"), default=1
)
library: Mapped["MusicLibrary | None"] = relationship("MusicLibrary", back_populates="tracks")
```

### Alembic Migration

1. Create `music_libraries` table
2. Insert default: `(id=1, name="Main", enabled=True, is_default=True, sort_order=0)`
3. Add `library_id` to `tracks` with `server_default="1"`
4. Create index `ix_tracks_library_id`
5. Update all existing tracks: `UPDATE tracks SET library_id = 1 WHERE library_id IS NULL`

## 3. Detection Rules Engine

### Rule Format (JSON)

```json
{
  "genres": ["christmas", "holiday", "xmas"],
  "keywords": ["christmas", "xmas", "noel", "jingle"],
  "directory_prefixes": ["Christmas/", "Holiday Music/"],
  "artist_keywords": []
}
```

### Matching Logic: `backend/services/library_matcher.py`

```python
def match_library(parsed: dict, libraries: list[MusicLibrary]) -> int:
    """Return library_id for a track. First match wins (sorted by sort_order)."""
```

Priority within each library:
1. **Directory prefix** -- file_path starts with any prefix (case-insensitive)
2. **Genre match** -- genre contains any genre keyword
3. **Keyword match** -- any keyword in title, artist, or album

If no match, returns default library (is_default=True).

Libraries sorted by `sort_order` -- specific libraries (Christmas) ordered before broad ones (Main).

## 4. Scanner Changes

### `scan_library()` in `backend/services/scanner.py`

1. Load all `MusicLibrary` rows at scan start (sorted by sort_order)
2. After `parse_audio_file()`, call `match_library(parsed, libraries)` to get `library_id`
3. Set `library_id` on new and updated Track objects

### `import_downloaded_file()`

Same: parse then `match_library()` then set `library_id`.

Performance: library list is small (2-5 entries), loaded once. Zero extra DB queries per track.

## 5. Subsonic Endpoint Filtering

### Shared Filter Helper: `backend/subsonic/library_filter.py`

```python
async def get_enabled_library_ids(db: AsyncSession) -> set[int]:
    result = await db.execute(
        select(MusicLibrary.id).where(MusicLibrary.enabled == True)
    )
    return {row[0] for row in result.all()}

def filter_tracks_by_library(query, enabled_ids: set[int]):
    return query.where(Track.library_id.in_(enabled_ids))

def filter_albums_by_library(query, enabled_ids: set[int]):
    has_enabled_track = exists(
        select(Track.id).where(Track.album_id == Album.id, Track.library_id.in_(enabled_ids))
    )
    return query.where(has_enabled_track)

def filter_artists_by_library(query, enabled_ids: set[int]):
    has_enabled_track = exists(
        select(Track.id).where(Track.artist_id == Artist.id, Track.library_id.in_(enabled_ids))
    )
    return query.where(has_enabled_track)

def get_library_filter_ids(request, enabled_ids: set[int]) -> set[int]:
    """If musicFolderId specified, use only that library. Otherwise all enabled."""
    folder_id = request.query_params.get("musicFolderId")
    if folder_id:
        fid = int(folder_id)
        return {fid} if fid in enabled_ids else set()
    return enabled_ids
```

### Endpoint-by-Endpoint Changes

**`backend/subsonic/browsing.py`:**

| Endpoint | Change |
|----------|--------|
| `getMusicFolders` | Return all libraries from DB (enabled AND disabled per Subsonic spec) |
| `getIndexes` | Filter artists by enabled libraries + respect musicFolderId |
| `getArtists` | Same as getIndexes |
| `getArtist` | Filter album list to albums with tracks in enabled libraries |
| `getAlbum` | Filter tracks within album by enabled libraries |
| `getMusicDirectory` | Filter children by enabled libraries |
| `getSong` | No filter (direct ID access) |
| `getGenres` | Filter genre counts to enabled libraries |
| `getSimilarSongs2` | Filter result tracks |
| `getTopSongs` | Filter result tracks |

**`backend/subsonic/search.py`:**

| Endpoint | Change |
|----------|--------|
| `search3` | Filter all three result sets (artists, albums, songs). Critical for Symfonium fast sync. |

**`backend/subsonic/lists.py`:**

| Endpoint | Change |
|----------|--------|
| `getAlbumList2` | Filter albums + respect musicFolderId |
| `getRandomSongs` | Filter tracks + respect musicFolderId |
| `getSongsByGenre` | Filter tracks + respect musicFolderId |
| `getStarred2` | Filter all three sets |

**No filter needed:**
- `stream`, `download`, `getCoverArt` (direct ID access)
- `star`, `unstar`, `scrobble` (operate on specific IDs)

**`backend/subsonic/playlists_api.py`:**
- `getPlaylist`: Filter track entries by enabled libraries (show playlist with gaps)

### Implementation Pattern

Each endpoint gets ~2 lines:
```python
enabled_ids = await get_enabled_library_ids(db)
lib_ids = get_library_filter_ids(request, enabled_ids)
query = filter_tracks_by_library(query, lib_ids)
```

## 6. Backend API: `backend/api/libraries.py`

```
GET    /api/libraries              -- List all with track counts
POST   /api/libraries              -- Create library
GET    /api/libraries/{id}         -- Get details
PUT    /api/libraries/{id}         -- Update (name, rules, enabled, color, icon, sort_order)
DELETE /api/libraries/{id}         -- Delete (reassign tracks to default)
POST   /api/libraries/{id}/toggle  -- Quick enable/disable
POST   /api/libraries/reassign     -- Re-run detection on all tracks
```

### Business Rules

- Cannot delete the default library
- Deleting non-default moves its tracks to default
- Only one `is_default=True` at a time
- Cannot disable all libraries (at least one must remain enabled)
- Changing detection rules does NOT auto-reassign; user must click "Reassign"

Register in `backend/main.py`:
```python
from backend.api import libraries
app.include_router(libraries.router, prefix="/api/libraries", tags=["libraries"])
```

## 7. Frontend

### 7.1 Settings Page: Music Libraries Card

Add to `frontend/src/routes/settings/+page.svelte`:

- List of libraries: colored dot, name, track count, enabled toggle, edit/delete
- "Add Library" form: name, color picker, icon selector
- Per-library expandable detection rules: genres, keywords, directory prefixes (comma-separated inputs)
- "Reassign All Tracks" button
- Default library badge (non-deletable)

### 7.2 Sidebar Library Selector

Add to `frontend/src/components/Sidebar.svelte` between logo and nav:

```svelte
<div class="px-3 pb-2">
  <div class="flex flex-wrap gap-1">
    {#each libraries as lib}
      <button onclick={() => toggleLibrary(lib.id)}
        class="px-2 py-0.5 text-[10px] rounded-full transition-all
          {lib.enabled ? 'bg-opacity-20 text-white' : 'text-[var(--text-disabled)] line-through'}"
        style="background-color: {lib.enabled ? lib.color + '33' : 'transparent'};
               border: 1px solid {lib.enabled ? lib.color : 'var(--border-subtle)'}">
        {lib.name}
      </button>
    {/each}
  </div>
</div>
```

### 7.3 Library Page

Show colored dot/badge per track indicating which library it belongs to.

### 7.4 Stores

```javascript
export const musicLibraries = writable([]);
```
Load in `+layout.svelte` on mount.

## 8. Config

No toml changes. Libraries are entirely database-driven (managed via web UI), following the ScheduleTask pattern.

Default library seeded in `init_db()`:
```python
if not existing_default:
    session.add(MusicLibrary(id=1, name="Main", enabled=True, is_default=True, sort_order=0))
```

## 9. Symfonium Integration

### getMusicFolders

Return all libraries from DB:
```python
return [{"id": str(lib.id), "name": lib.name} for lib in libraries]
```

All libraries appear in Symfonium's folder picker (enabled AND disabled). Content endpoints return nothing for disabled libraries.

### musicFolderId Parameter

Symfonium sends `musicFolderId` on: `getIndexes`, `getAlbumList2`, `getRandomSongs`, `getSongsByGenre`, `search3`. The `get_library_filter_ids` helper handles this transparently.

## 10. Implementation Steps (Phased)

### Phase 1: Schema + Model (Low Risk)
1. Create `MusicLibrary` model
2. Add `library_id` to Track
3. Register in `__init__.py`
4. Write migration with default library + backfill
5. Add default seeding to `init_db()`

### Phase 2: Detection Engine + Scanner (Medium Risk)
6. Create `library_matcher.py`
7. Modify `scan_library()` to call `match_library()`
8. Modify `import_downloaded_file()` similarly
9. Test: create Christmas library with genre rules, scan, verify classification

### Phase 3: Backend API (Low Risk)
10. Create `backend/api/libraries.py` with CRUD + toggle + reassign
11. Register router in `main.py`

### Phase 4: Subsonic Filtering (High Risk -- Most Critical)
12. Create `library_filter.py`
13. Update `getMusicFolders`
14. Add filtering to `getIndexes`, `getArtists`, `search3` (fast-sync critical)
15. Add filtering to `getAlbumList2`, `getRandomSongs`, `getSongsByGenre`, `getStarred2`
16. Add filtering to `getMusicDirectory`, `getGenres`, `getSimilarSongs2`
17. Add filtering to `getPlaylist`, `getBookmarks`, `getPlayQueue`
18. Test with Symfonium end-to-end

### Phase 5: Frontend (Low Risk)
19. Add `musicLibraries` store
20. Sidebar library selector toggle pills
21. Settings page library management card
22. Library badge on track listings
23. Detection rules editor

## 11. Edge Cases

| Case | Handling |
|------|----------|
| Track matches multiple rules | First-match-wins by `sort_order` |
| Track matches no rules | Falls through to default library |
| Re-scan behavior | Re-evaluates `match_library()` for every track, updates library_id |
| Default library deletion | Blocked (API returns 400) |
| All libraries disabled | Blocked (API returns 400, at least one must be enabled) |
| Track ID stability | MD5 of file path, unaffected by library assignment |
| Playlist with disabled-library tracks | Entries filtered from `getPlaylist` response; reappear when re-enabled |
| FTS index | Unaffected; library filter applied after FTS matching |
| Artist/Album visibility | Exist only if they have tracks in enabled libraries (subquery) |
| Analysis/enrichment | Run on all tracks regardless of library status |
| Downloaded tracks | Classified by `match_library()` during import |

## 12. Testing Checklist

### Database
- [ ] Migration applies on empty and existing DB
- [ ] All existing tracks have `library_id=1`
- [ ] Default "Main" library exists

### Detection
- [ ] Genre keyword matching works (case-insensitive)
- [ ] Directory prefix matching works
- [ ] First-match-wins ordering
- [ ] No-match falls to default

### Scanner
- [ ] New tracks get correct library_id
- [ ] Re-scan updates library_id on rule change
- [ ] Downloads get correct library_id

### API
- [ ] CRUD operations work
- [ ] Cannot delete default library
- [ ] Cannot disable last enabled library
- [ ] Toggle enable/disable works

### Subsonic
- [ ] getMusicFolders returns all libraries
- [ ] getIndexes respects musicFolderId
- [ ] search3 excludes disabled library tracks
- [ ] getRandomSongs excludes disabled tracks
- [ ] getAlbumList2 excludes disabled albums
- [ ] getStarred2 excludes disabled items
- [ ] getPlaylist filters entries
- [ ] stream/download still work for disabled tracks (direct ID)

### Symfonium
- [ ] Folders appear in folder picker
- [ ] Selecting folder filters content
- [ ] Disabling library + re-sync removes content
- [ ] Re-enabling + re-sync restores content

### Frontend
- [ ] Sidebar toggle pills work
- [ ] Settings library management works
- [ ] Library badges on tracks
