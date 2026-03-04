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
│   │   ├── routes/           # SvelteKit pages (11 routes)
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

## Key Patterns

- **Soulseek search**: 4-strategy fallback (full → cleaned → track-only → first-word)
- **Quality scoring**: FLAC preference, size/bitrate bonuses, per-user dedup
- **Text normalization**: `normalize_text()` strips accents, special chars for fuzzy matching
- **Cover art**: Deezer → Cover Art Archive → iTunes → Last.fm fallback chain
- **FTS5**: Full-text search populated during library scan, prefix matching
- **Transcoding**: ffmpeg streaming via `asyncio.create_subprocess_exec`
