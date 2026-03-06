# Remix & Alternate Version Discovery - Implementation Plan

## 1. Summary

Add the ability to discover remixes, dubs, edits, extended mixes, and other alternate versions of tracks already in the Zonik library. Three entry points:

1. **Per-track "Find Remixes"** -- new option in library track context menu (3-dot menu), opening a modal with results from Last.fm + Soulseek search, with inline download buttons.
2. **Batch discovery API endpoint** -- search for remixes across favorites (or recent additions), returning scored candidates.
3. **Scheduled task** -- periodically scan favorites for available remixes, storing results for the Discover page.

Follows existing patterns from "Find Similar" (context menu + modal), Discover page tabs, and `discover_similar` scheduled task.

## 2. Backend -- New Service

### `backend/services/remix_discovery.py`

**Version Type Detection Regex:**

```python
import re

VERSION_PATTERNS = [
    (r'\b(remix)\b', 'remix'),
    (r'\b(dub\s*mix|dub)\b', 'dub'),
    (r'\b(extended\s*mix|extended\s*version|extended)\b', 'extended'),
    (r'\b(club\s*mix|club\s*edit|club\s*version)\b', 'club'),
    (r'\b(radio\s*edit|radio\s*mix|radio\s*version)\b', 'radio_edit'),
    (r'\b(acoustic\s*version|acoustic\s*mix|acoustic)\b', 'acoustic'),
    (r'\b(instrumental)\b', 'instrumental'),
    (r'\b(a\s*cappella|acapella|a\s+capella)\b', 'acapella'),
    (r'\b(vip\s*mix|vip)\b', 'vip'),
    (r'\b(bootleg)\b', 'bootleg'),
    (r'\b(live\s*version|live\s*mix|live\b)', 'live'),
    (r'\b(remaster(?:ed)?)\b', 'remaster'),
    (r'\b(edit)\b', 'edit'),
    (r'\b(mix)\b', 'mix'),
    (r'\b(version)\b', 'version'),
]

def detect_version_type(title: str) -> str | None:
    for pattern, vtype in VERSION_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return vtype
    return None

def extract_base_title(title: str) -> str:
    """Strip remix/version parentheticals to get base track name."""
    cleaned = re.sub(
        r'\s*[\(\[].*?(?:remix|mix|version|edit|remaster|dub|acoustic|instrumental|vip|bootleg|live|a\s*cappella|acapella).*?[\)\]]',
        '', title, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r'\s*-\s*(?:.*?remix|.*?mix|.*?version|.*?edit|.*?remaster|.*?dub)$',
        '', cleaned, flags=re.IGNORECASE
    )
    return cleaned.strip()

def extract_remixer(title: str) -> str | None:
    m = re.search(r'[\(\[](.*?)\s+(?:remix|mix|edit|dub|version)[\)\]]', title, re.IGNORECASE)
    return m.group(1).strip() if m else None
```

**Core Search Functions:**

```python
async def find_remixes_lastfm(artist: str, track: str, limit: int = 30) -> list[dict]:
    base_title = extract_base_title(track)
    queries = [
        f"{artist} {base_title} remix",
        f"{artist} {base_title} mix",
        f"{artist} {base_title} edit",
        f"{base_title} remix",  # catch remixes credited to remixer
    ]
    results = []
    seen: set[str] = set()
    for query in queries:
        tracks = await lastfm.search_tracks(query, limit=limit)
        for t in tracks:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key in seen:
                continue
            seen.add(key)
            # Must be a version of the same base track
            t_base = extract_base_title(t['name'])
            if not _is_same_base_track(base_title, t_base, artist, t['artist']):
                continue
            # Skip exact same version as original
            if normalize_text(t['name']) == normalize_text(track) and normalize_text(t['artist']) == normalize_text(artist):
                continue
            vtype = detect_version_type(t['name'])
            remixer = extract_remixer(t['name'])
            results.append({**t, 'version_type': vtype or 'alternate', 'remixer': remixer, 'base_title': base_title, 'source': 'lastfm'})
    return results[:limit]

def _is_same_base_track(base1: str, base2: str, artist1: str, artist2: str) -> bool:
    b1, b2 = normalize_text(base1), normalize_text(base2)
    if b1 == b2:
        return True
    if len(b1) > 3 and len(b2) > 3:
        if b1 in b2 or b2 in b1:
            return True
    return False
```

## 3. API Endpoint

### `GET /api/discovery/remixes`

Add to existing `backend/api/discovery.py`:

```
Params: artist, track, limit=30, sources=lastfm,soulseek
```

**Response:**
```json
{
  "remixes": [
    {
      "name": "Midnight City (Eric Prydz Remix)",
      "artist": "M83",
      "version_type": "remix",
      "remixer": "Eric Prydz",
      "base_title": "Midnight City",
      "source": "lastfm",
      "listeners": 45000,
      "in_library": false,
      "track_id": null
    }
  ],
  "total": 2,
  "in_library": 0,
  "source_artist": "M83",
  "source_track": "Midnight City"
}
```

Library matching follows existing pattern in `similar_by_track` endpoint (join Track + Artist, case-insensitive).

## 4. Scheduled Task

### Registration in `backend/api/schedule.py`

```python
# DEFAULT_TASKS:
{"task_name": "discover_remixes", "interval_hours": 168, "run_at": "05:30", "count": 20},

# TASK_LABELS:
"discover_remixes": "Discover Remixes",

# TASK_DESCRIPTIONS:
"discover_remixes": "Search for remixes, dubs, edits, and alternate versions of your favorite tracks.",
```

### Implementation in `backend/workers/scheduler.py`

Add `_run_discover_remixes` following `_run_discover_similar` pattern:

```python
async def _run_discover_remixes(db: AsyncSession, job: Job, count: int = 20):
    from backend.services.remix_discovery import find_remixes_lastfm
    favorites = (await db.execute(
        select(Favorite).options(
            selectinload(Favorite.track).selectinload(Track.artist)
        ).where(Favorite.track_id.isnot(None)).limit(count)
    )).scalars().all()

    missing = []
    in_library = 0
    seen: set[str] = set()
    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        # Skip tracks that are themselves remixes
        if detect_version_type(fav.track.title):
            continue
        remixes = await find_remixes_lastfm(fav.track.artist.name, fav.track.title, limit=10)
        for t in remixes:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key in seen:
                continue
            seen.add(key)
            result = await db.execute(
                select(Track).join(Artist, Track.artist_id == Artist.id).where(
                    Track.title.ilike(t["name"]), Artist.name.ilike(t["artist"]),
                ).limit(1)
            )
            if result.scalar_one_or_none():
                in_library += 1
            else:
                missing.append({
                    "artist": t["artist"], "track": t["name"], "status": "missing",
                    "version_type": t.get("version_type", "remix"),
                    "remixer": t.get("remixer"),
                    "source": f"{fav.track.artist.name} - {fav.track.title}",
                })
    job.total = len(seen)
    job.progress = in_library
    job.tracks = json.dumps(missing)
    job.result = json.dumps({"favorites_checked": len(favorites), "remixes_found": len(seen), "in_library": in_library, "missing": len(missing)})
```

Add dispatch case in `run_task`:
```python
elif task_name == "discover_remixes":
    await _run_discover_remixes(db, job, count=count or 20)
```

Add to auto-download condition:
```python
and task_name in ("lastfm_top_tracks", "discover_similar", "discover_remixes")
```

## 5. Frontend

### 5.1 Library Context Menu: "Find Remixes"

Add to `frontend/src/routes/library/+page.svelte` 3-dot menu, after "Find Similar":

```svelte
<button onclick={() => { const t = menuTrack; closeMenu(); findRemixes(t); }}>
    <Disc3 class="w-3.5 h-3.5 text-green-400" /> Find Remixes
</button>
```

New state + functions:
```javascript
let showRemixes = $state(false);
let remixSource = $state(null);
let remixResults = $state([]);
let remixLoading = $state(false);

async function findRemixes(track) {
    remixSource = track;
    showRemixes = true;
    remixLoading = true;
    const data = await fetch(`/api/discovery/remixes?artist=${encodeURIComponent(track.artist)}&track=${encodeURIComponent(track.title)}&limit=30`).then(r => r.json());
    remixResults = data.remixes || [];
    remixLoading = false;
}
```

Modal follows "Find Similar" pattern with version type badges and download buttons.

### 5.2 Discover Page: "Remixes" Tab

Add to `frontend/src/routes/discover/+page.svelte`:

```javascript
const tabs = [
    { key: 'top', label: 'Top Tracks', icon: TrendingUp },
    { key: 'similar', label: 'Similar Tracks', icon: Music },
    { key: 'artists', label: 'Similar Artists', icon: Users },
    { key: 'remixes', label: 'Remixes', icon: Disc3 },
    { key: 'search', label: 'Search', icon: Search },
];
```

Loads cached results from last `discover_remixes` job. Each row shows: track name with version type badge, artist, remixer, source track reference, download status.

### 5.3 Version Type Badge Colors

```javascript
const VERSION_COLORS = {
    remix: 'bg-green-500/20 text-green-400',
    dub: 'bg-purple-500/20 text-purple-400',
    extended: 'bg-blue-500/20 text-blue-400',
    club: 'bg-cyan-500/20 text-cyan-400',
    radio_edit: 'bg-yellow-500/20 text-yellow-400',
    acoustic: 'bg-amber-500/20 text-amber-400',
    instrumental: 'bg-pink-500/20 text-pink-400',
    vip: 'bg-indigo-500/20 text-indigo-400',
    bootleg: 'bg-orange-500/20 text-orange-400',
    live: 'bg-emerald-500/20 text-emerald-400',
    remaster: 'bg-slate-500/20 text-slate-400',
};
```

### 5.4 Schedule Page

Add `discover_remixes` to the Discover section task group.

## 6. Implementation Steps

### Phase 1: Backend Core
1. Create `backend/services/remix_discovery.py` (regex, search functions)
2. Add `GET /api/discovery/remixes` to `backend/api/discovery.py`
3. Test endpoint with curl

### Phase 2: Scheduled Task
4. Add to `DEFAULT_TASKS`, `TASK_LABELS`, `TASK_DESCRIPTIONS` in schedule.py
5. Add `_run_discover_remixes` to scheduler.py + dispatch + auto_download
6. Test scheduled task run

### Phase 3: Frontend -- Library
7. Add "Find Remixes" to context menu
8. Add remix modal with version type badges + download buttons

### Phase 4: Frontend -- Discover
9. Add "Remixes" tab to Discover page with cached job results
10. Add ScheduleControl + "Download All Missing"
11. Add to schedule page Discover section

## 7. Edge Cases

| Case | Handling |
|------|----------|
| Avoiding duplicates | `normalize_text(artist + name)` as seen-key; exclude original track |
| Remix of remix | Skip source tracks where `detect_version_type` returns a value in batch mode |
| Artist variations | Remixes credited to remixer caught via `base_title remix` query without artist |
| Rate limiting | Last.fm 0.35s rate limit already enforced; 20 favorites x 4 queries = ~25s for batch |
| False positives | `_is_same_base_track` requires base title word overlap |
| Empty results | EmptyState component in modal; `remixes_found: 0` in scheduled task result |
| Blacklisted artists | Filter during candidate sourcing |

## 8. Testing Checklist

### Backend
- [ ] `detect_version_type` classifies: "(X Remix)", "(Extended Mix)", "(Dub)", "(Radio Edit)", "(VIP)", "(Acoustic)", "(Instrumental)", "(Live)"
- [ ] `extract_base_title` strips: "(X Remix)", "[Extended Mix]", "- Radio Edit"
- [ ] `extract_remixer` extracts: "X" from "(X Remix)", None from "(Extended Mix)"
- [ ] `_is_same_base_track` matches normalized base titles
- [ ] `find_remixes_lastfm` returns results for well-known tracks
- [ ] `GET /api/discovery/remixes` returns annotated results with `in_library` flags
- [ ] Scheduled task creates Job with version_type in tracks JSON
- [ ] Original track excluded from results
- [ ] Remix source tracks skipped in batch mode

### Frontend
- [ ] "Find Remixes" appears in library context menu
- [ ] Modal shows loading skeleton then results with version type badges
- [ ] "Get" button triggers download, "Get All Missing" works
- [ ] "In Library" badge shown for already-downloaded remixes
- [ ] Discover "Remixes" tab loads cached results
- [ ] ScheduleControl for `discover_remixes` works
- [ ] Empty state for no remixes found
