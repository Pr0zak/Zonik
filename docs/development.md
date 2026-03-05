# Development Guide

## Project Structure

```
zonik/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py             # Settings from zonik.toml
│   ├── database.py           # SQLAlchemy engine, FTS5
│   ├── models/               # SQLAlchemy models (14 models)
│   ├── api/                  # REST API routes
│   ├── subsonic/             # OpenSubsonic API implementation
│   ├── services/             # Business logic
│   ├── workers/              # ARQ background tasks
│   └── migrations/           # Alembic migrations
├── frontend/
│   ├── src/
│   │   ├── components/       # Svelte components
│   │   │   ├── ui/           # 8 reusable UI components
│   │   │   ├── Sidebar.svelte
│   │   │   ├── Player.svelte
│   │   │   └── Toast.svelte
│   │   ├── routes/           # SvelteKit pages (12 routes)
│   │   └── lib/              # API client, stores, utils
│   └── static/
├── deploy/                   # Systemd service files
├── docs/                     # Documentation
├── install.sh                # Production installer
├── upgrade.sh                # Upgrade script
├── zonik.toml.example        # Config template
└── pyproject.toml
```

## Running Locally

```bash
# Terminal 1: Backend
uv run uvicorn backend.main:app --reload --port 8000

# Terminal 2: Frontend (proxies /api and /rest to :8000)
cd frontend && npm run dev

# Terminal 3: Worker (optional, needs Redis)
uv run arq backend.workers.WorkerSettings
```

Frontend dev server runs on http://localhost:5173 and proxies API calls to the backend on :8000.

## Database

SQLite with WAL mode. Tables are auto-created on startup via `init_db()`.

### Models

- **Track** - Core entity, ID = MD5 of relative file path
- **Artist** - ID = MD5 of `artist:<name>`
- **Album** - ID = MD5 of `album:<title>:<artist>`
- **Playlist / PlaylistTrack** - Manual and auto-generated playlists
- **Favorite** - Starred tracks/albums/artists
- **TrackAnalysis** - BPM, key, energy, danceability
- **TrackEmbedding** - 512-dim CLAP vector (BLOB)
- **Job** - Background job history
- **User** - Subsonic auth (bcrypt passwords)
- **PlayQueue / Bookmark** - Subsonic state
- **ScheduleTask** - Scheduled task configuration
- **DownloadBlacklist** - Blocked artists/tracks

### Migrations

```bash
# Generate migration after model changes
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head
```

## Adding a Subsonic Endpoint

1. Add the route to the appropriate file in `backend/subsonic/`
2. Use `@router.get("/endpointName")` and `@router.get("/endpointName.view")`
3. Use `subsonic_response()` for success, `error_response()` for errors
4. Use `format_track()`, `format_album()`, `format_artist()` helpers
5. Test with: `curl http://localhost:8000/rest/endpointName?f=json&u=admin&p=admin`

## Adding a Frontend Page

1. Create `frontend/src/routes/<name>/+page.svelte`
2. Add navigation entry in `frontend/src/components/Sidebar.svelte`
3. Use `$state()` for reactive state (Svelte 5 runes)
4. Use `fetch('/api/...')` or `api.*()` from `$lib/api.js`

## Adding a UI Component

Reusable UI components live in `frontend/src/components/ui/`. The 8 existing components are:

| Component | Description |
|-----------|-------------|
| `Button` | 6 variants (primary, secondary, danger, ghost, outline, icon) |
| `Badge` | 5 variants (default, success, warning, error, info) |
| `Card` | Container with consistent padding and background |
| `Skeleton` | Loading placeholder with shimmer animation |
| `FormInput` | Label + input with optional eye toggle for secrets |
| `Modal` | Dialog overlay with backdrop blur |
| `EmptyState` | Icon + message for empty lists |
| `PageHeader` | Page title with optional actions slot |

To add a new component:

1. Create `frontend/src/components/ui/MyComponent.svelte`
2. Use CSS variables from the design system (`--bg-primary`, `--bg-secondary`, `--text-primary`, etc.)
3. Use lucide-svelte for icons
4. Export props using Svelte 5 `$props()` rune
5. Import where needed: `import MyComponent from '$components/ui/MyComponent.svelte'`

## UI Design System

The frontend uses a CSS variable-based design system defined in `frontend/src/app.css`:

- **Backgrounds**: Layered from `--bg-primary` (#0a0a0a) through `--bg-secondary`, `--bg-tertiary`, to `--bg-hover`
- **Section colors**: Each route has a unique accent color (dashboard=indigo, library=purple, discover=green, downloads=blue, playlists=amber, favorites=red, analysis=pink, stats=cyan, schedule=orange, logs=violet, settings=slate)
- **Typography**: Inter font via Google Fonts CDN
- **Icons**: lucide-svelte (tree-shakeable SVG icons) used throughout

## WebSocket Real-Time Updates

The WebSocket connection (`/api/ws`) provides real-time job progress updates:

- Connected in `+layout.svelte` on mount
- `broadcast_job_update()` is called in `download.py` and `library.py` for downloads and scans
- Active jobs are tracked in `stores.js` via the `activeJobs` store
- Sidebar footer shows a spinning loader with active job count (clickable, links to /logs)
- Library scan broadcasts progress every 50 files; job result stored as JSON
- **Important**: Use `_clients.difference_update()` not `_clients -=` in websocket.py (augmented assignment creates local variable scope issue)

Message format:
```json
{
  "id": "job-uuid",
  "type": "download",
  "status": "running",
  "progress": 3,
  "total": 10
}
```

## Key Patterns

- **Soulseek search**: 4-strategy fallback (full -> cleaned -> track-only -> first-word)
- **Soulseek retry**: `search_and_download` tries up to 5 candidates before failing
- **Quality scoring**: FLAC preference, size/bitrate bonuses, per-user dedup
- **Text normalization**: `normalize_text()` strips accents, special chars for fuzzy matching
- **Cover art**: Deezer -> Cover Art Archive -> iTunes -> Last.fm fallback chain
- **FTS5**: Full-text search populated during library scan, prefix matching
- **Transcoding**: ffmpeg streaming via `asyncio.create_subprocess_exec`
- **SQLite single writer**: Never use concurrent sessions for writes; progress updates go via WebSocket only
- **db.get() for dedup**: Use `await db.get(Model, id)` in get_or_create patterns to check identity map first
- **URLSearchParams**: Always filter out undefined/null values before passing to `new URLSearchParams()` — it converts them to literal strings
- **Cover art**: Library card views use `/rest/getCoverArt?id=<album_id>` for thumbnails
