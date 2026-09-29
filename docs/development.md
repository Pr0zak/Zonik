# Development Guide

## Project Structure

Zonik is a monorepo: the Python backend and SvelteKit web UI at the root, the Android apps under `mobile/`.

```
zonik/
├── backend/
│   ├── main.py               # FastAPI app entry point
│   ├── config.py             # Settings from zonik.toml
│   ├── database.py           # SQLAlchemy engine, init_db(), FTS5
│   ├── models/               # SQLAlchemy models
│   ├── api/                  # REST API routes (/api/*) + WebSocket
│   ├── subsonic/             # OpenSubsonic API implementation (/rest/*)
│   ├── soulseek/             # Native Soulseek P2P client
│   │   ├── protocol/         # Binary encode/decode, TCP framing
│   │   ├── client.py         # Client orchestrator
│   │   ├── server_conn.py    # Server connection + auto-reconnect
│   │   ├── peer.py           # Peer connections
│   │   ├── listener.py       # Inbound peer listener
│   │   ├── transfer.py       # Download state machine
│   │   ├── search.py         # Multi-strategy search
│   │   ├── shares.py         # Shared-file index
│   │   └── reputation.py     # Peer reliability tracking
│   ├── services/             # Business logic (scanner, enrichment, analyzer, ...)
│   │   └── ai/               # AI features (NL search, playlist generation, tagging)
│   ├── middleware/           # Rate limiting
│   ├── workers/              # ARQ background tasks + scheduler
│   └── migrations/           # Alembic environment + versions/
├── frontend/                 # SvelteKit 5 (runes), Tailwind, adapter-static
│   ├── src/
│   │   ├── components/       # Sidebar, TopBar, Player, Toast, ...
│   │   │   ├── ui/           # Reusable UI components
│   │   │   ├── map/          # Music Map views
│   │   │   └── stats/        # Stats widgets
│   │   ├── routes/           # SvelteKit pages
│   │   └── lib/              # API client, stores, websocket, utils
│   └── static/
├── mobile/                   # Gradle project (Kotlin / Jetpack Compose)
│   ├── app/                  # Phone app (+ Android Auto, Chromecast, Google TV)
│   ├── wear/                 # Standalone Pixel Watch player
│   └── core/                 # Shared Subsonic API, models, auth
├── scripts/                  # Dev helpers (capture-screenshots.mjs)
├── deploy/                   # systemd units (zonik-web, zonik-worker)
├── docs/                     # Documentation + screenshots
├── .github/workflows/        # mobile-release.yml (app-v* tags)
├── alembic.ini               # Alembic config (script_location = backend/migrations)
├── install.sh                # Production installer
├── upgrade.sh                # Production upgrade script
├── zonik.toml.example        # Config template
├── pyproject.toml            # Backend package + version
└── uv.lock
```

## Running Locally

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js, ffmpeg, and Redis (for the worker).

```bash
# One-time setup
uv sync                                   # add --extra analysis / --extra clap for Essentia / CLAP
cp zonik.toml.example zonik.toml          # then point library/database/cache paths at local dirs
cd frontend && npm install && cd ..
```

The backend reads `./zonik.toml` first, then `/etc/zonik/zonik.toml`. `zonik.toml` is gitignored.

```bash
# Terminal 1: Backend
uv run uvicorn backend.main:app --reload --port 8000

# Terminal 2: Frontend (proxies /api and /rest to :8000)
cd frontend && npm run dev

# Terminal 3: Worker (optional, needs Redis at [redis].url)
uv run arq backend.workers.WorkerSettings
```

The frontend dev server runs on http://localhost:5173 and proxies API calls to the backend on :8000 (see `frontend/vite.config.js`). In production the backend serves the built SPA (`npm run build` → `frontend/build/`) itself on port 3000.

## Tests

There is no backend or frontend test suite. Before committing, check that the backend imports and the frontend builds:

```bash
uv run python -c "import backend.main"
cd frontend && npm run build
```

The mobile app has Paparazzi screenshot tests (JVM, no emulator) in `mobile/app/src/test/.../screenshots/`:

```bash
cd mobile
./gradlew :app:recordPaparazziDebug --tests '*ScreensTest*'   # writes app/src/test/snapshots/images/
./gradlew :app:verifyPaparazziDebug --tests '*ScreensTest*'
```

Web UI screenshots for the README are captured with Playwright:

```bash
node scripts/capture-screenshots.mjs http://<your-server>:3000   # saves to docs/screenshots/
```

## Database

SQLite with WAL mode (path from `[database].path`). On startup, `init_db()` creates any **missing tables** and the FTS5 index, but it does not alter existing tables — schema changes to existing tables need an Alembic migration.

### Models

- **Track** - Core entity, ID = MD5 of relative file path
- **Artist / Album** - ID = MD5-derived from name (album: title + artist)
- **Playlist / PlaylistTrack** - Manual and auto-generated playlists
- **Favorite** - Starred tracks/albums/artists
- **TrackAnalysis / TrackMood** - BPM, key, energy, danceability; mood tags
- **TrackEmbedding** - 512-dim CLAP vector (BLOB)
- **PlayHistory / TasteProfile / Recommendation** - Listening history and discovery
- **TrackUpgrade** - Quality-upgrade pipeline
- **Job** - Background job history
- **User** - Subsonic auth (bcrypt passwords)
- **PlayQueue / Bookmark** - Subsonic state
- **ScheduleTask** - Scheduled task configuration
- **DownloadBlacklist** - Blocked artists/tracks
- **AppLog** - Logs uploaded by the mobile apps (`/api/logs`)
- **AIUsage** - AI feature token/cost tracking
- **SoulseekSnapshot** - Soulseek stats history

### Migrations

Migrations live in `backend/migrations/versions/`. `env.py` takes the database path from `zonik.toml`, and uses batch mode for SQLite.

```bash
# Generate migration after model changes (review the generated file)
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head
```

`upgrade.sh` only runs `init_db()`, not Alembic. After deploying a migration that changes an existing table, run `alembic upgrade head` on the server as well.

## Mobile Development

The Gradle root is `mobile/` (modules `:app`, `:wear`, `:core`). You need JDK 17 and the Android SDK:

```bash
cd mobile
export JAVA_HOME=/path/to/jdk-17
export ANDROID_HOME=/path/to/android-sdk

./gradlew :app:assembleDebug     # phone APK  -> app/build/outputs/apk/debug/app-debug.apk
./gradlew :wear:assembleDebug    # watch APK  -> wear/build/outputs/apk/debug/wear-debug.apk
./gradlew assembleDebug          # both
```

Local builds are signed with `~/.android/debug.keystore`. CI builds use the keystore from the `DEBUG_KEYSTORE_BASE64` repo secret, so the signatures differ. To install a local build over a CI build, uninstall the CI build first. Phone and watch share `applicationId = "com.zonik.app"`, which Wear Data Layer pairing requires, so don't change it. See [`mobile/README.md`](../mobile/README.md) for install and pairing details.

## Releases and Tags

Backend and mobile are versioned and tagged separately. Don't create bare `vX.Y.Z` tags. They are legacy, from before the monorepo.

| Component | Version lives in | Tag |
|-----------|------------------|-----|
| Backend + web UI | `pyproject.toml` and `frontend/package.json` (keep in sync) | `server-vX.Y.Z` |
| Mobile (phone + watch) | `versionCode` / `versionName` in `mobile/app/build.gradle.kts` | `app-vX.Y.Z` |

```bash
git tag server-vX.Y.Z && git push origin server-vX.Y.Z   # backend
git tag app-vX.Y.Z    && git push origin app-vX.Y.Z      # mobile
```

Push each tag on its own. Don't use `git push --tags`.

- **Backend:** no CI. Servers pick up changes by running `upgrade.sh` as root in the install directory. It pulls `main`, reinstalls Python deps, rebuilds the frontend, runs `init_db()`, and restarts `zonik-web` and `zonik-worker`. `SKIP_RESTART=1` skips the restart.
- **Mobile:** `.github/workflows/mobile-release.yml` runs on `app-v*` tags. It can also be started by hand with an existing tag. It runs `./gradlew assembleDebug` in `mobile/` and attaches `zonik-vX.Y.Z-debug.apk` and `zonik-wear-vX.Y.Z-debug.apk` to the matching GitHub release.

## Adding a Subsonic Endpoint

1. Add the route to the appropriate file in `backend/subsonic/`
2. Use `@router.get("/endpointName")` and `@router.get("/endpointName.view")`
3. Use `subsonic_response()` for success, `error_response()` for errors
4. Use `format_track()`, `format_album()`, `format_artist()` helpers
5. Test with: `curl 'http://localhost:8000/rest/endpointName?f=json&u=<user>&p=<password>'`

## Adding a Frontend Page

1. Create `frontend/src/routes/<name>/+page.svelte`
2. Add navigation entry in `frontend/src/components/Sidebar.svelte`
3. Use `$state()` for reactive state (Svelte 5 runes)
4. Use `fetch('/api/...')` or `api.*()` from `$lib/api.js`
5. Wrap the page toolbar in `Toolbar` and use `StatTile` / `DataTable` for headline numbers and sortable tables

## Adding a UI Component

Reusable UI components live in `frontend/src/components/ui/`:

| Component | Description |
|-----------|-------------|
| `Button` | 6 variants (primary, secondary, danger, ghost, outline, icon) |
| `Badge` | 5 variants (default, success, warning, error, info) |
| `Card` | Container with consistent padding and background |
| `Skeleton` | Loading placeholder with shimmer animation |
| `FormInput` | Label + input with optional eye toggle for secrets |
| `Toggle` | On/off switch (sm/md/lg) |
| `Modal` | Dialog overlay with backdrop blur |
| `EmptyState` | Icon + message for empty lists |
| `PageHeader` | Page title with optional actions slot |
| `Toolbar` | Sticky two-row page toolbar (left/right snippets) |
| `StatTile` | Headline-number tile with tone (default/good/warn/bad), optional link |
| `DataTable` | Sortable table with column definitions and row snippet |
| `StarRating` | 5-star rating input |
| `SwipeRow` | Swipeable list row with actions |
| `ScheduleControl` | Schedule task toggle and config |
| `ScheduleSection` | Collapsible "Schedule & Automation" wrapper |
| `Pagination` | Page navigation controls |
| `CoverArt` | Album/track cover art with fallback |
| `FilterPills` | Horizontal filter chip bar |
| `FormatBadge` | Audio format indicator badge |

To add a new component:

1. Create `frontend/src/components/ui/MyComponent.svelte`
2. Use CSS variables from the design system (`--bg-primary`, `--surface-base`, `--text-primary`, etc.)
3. Use lucide-svelte for icons
4. Export props using Svelte 5 `$props()` rune
5. Import with a relative path where needed, e.g. `import MyComponent from '../../components/ui/MyComponent.svelte'`

## UI Design System

The frontend uses a CSS variable-based design system defined in `frontend/src/app.css`:

- **Backgrounds**: Layered from `--bg-primary` (#0a0a0a) through `--bg-secondary`, `--bg-tertiary`, `--bg-hover`, `--bg-active`, plus `--surface-*` container tokens
- **Section colors**: Each route has a unique accent color (dashboard=indigo, library=purple, discover=green, downloads=blue, playlists=amber, favorites=red, analysis=pink, stats=cyan, schedule=orange, logs=violet, settings=slate)
- **Typography**: Inter font via Google Fonts (loaded in `app.html`)
- **Icons**: lucide-svelte (tree-shakeable SVG icons) used throughout

## WebSocket Real-Time Updates

The WebSocket connection (`/api/ws`) provides real-time updates:

- Connected in `+layout.svelte` on mount
- **Job updates**: `broadcast_job_update()` called from the job-running API modules (`download.py`, `library.py`, `analysis.py`, `recommendations.py`, `jobs.py`) and `workers/scheduler.py`. Tracked in `activeJobs` store
- **Transfer progress**: `broadcast_transfer_progress()` called from native Soulseek client (500ms throttle). Tracked in `activeTransfers` store
- On connect: server sends current active jobs + current transfers
- Sidebar footer: spinning loader for active jobs (links to /logs), mini progress bar for active transfers (links to /downloads)
- Library scan broadcasts progress every 50 files; job result stored as JSON

Message types: `job_update`, `transfer_progress`, `log_entry`, `ping`

## Key Patterns

- **Soulseek**: Two backends — native P2P client (`backend/soulseek/`) or legacy slskd HTTP API. Selected by `soulseek.use_native`, which saving settings from the web UI always turns on. `services/soulseek.py` is a facade that routes to the active backend
- **Native Soulseek architecture**: Persistent singleton in FastAPI lifespan. Protocol layer (struct.pack/unpack) → Server connection (auto-reconnect) → Peer connections (direct+indirect race) → Transfer state machine (aiofiles)
- **Soulseek search**: 4-strategy fallback (full -> cleaned -> track-only -> first-word)
- **Soulseek retry**: `search_and_download` tries up to 5 candidates before failing
- **Peer reputation**: Redis-backed (in-memory fallback). 3 failures = 24h block. Adjusts quality scoring
- **Quality scoring**: FLAC preference, size/bitrate bonuses, per-user dedup, peer speed/slots bonus (native)
- **Text normalization**: `normalize_text()` strips accents, special chars for fuzzy matching
- **Cover art**: Deezer -> Cover Art Archive -> iTunes -> Last.fm fallback chain
- **FTS5**: Full-text search populated during library scan, prefix matching
- **Transcoding**: ffmpeg streaming via `asyncio.create_subprocess_exec`
- **Enrichment**: Per-track 45s timeout, concurrent MB+Last.fm lookups, cover art 20s timeout, cancel support
- **Essentia process pool**: Runs in `ProcessPoolExecutor` (CPU count - 1 workers, nice 15). Pool resets on both `BrokenProcessPool` and `TimeoutError` — hung workers can't be cancelled via `asyncio.wait_for`, so the entire pool must be recreated. Jobs abort after 20 consecutive failures to avoid grinding for hours on a dead pool.
- **SQLite single writer**: Never use concurrent sessions for writes; progress updates go via WebSocket only
- **db.get() for dedup**: Use `await db.get(Model, id)` in get_or_create patterns to check identity map first
- **URLSearchParams**: Always filter out undefined/null values before passing to `new URLSearchParams()` — it converts them to literal strings
- **Cover art**: Library card views use `/rest/getCoverArt?id=<album_id>` for thumbnails
