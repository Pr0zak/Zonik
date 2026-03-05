# Zonik

Self-hosted music backend serving Symfonium via OpenSubsonic API.

## Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 async + SQLite (WAL+FTS5) + ARQ/Redis
- **Frontend**: SvelteKit 5 + Tailwind CSS (dark theme, 12 routes)
- **Audio**: mutagen (tags), Essentia (analysis), CLAP (vibe embeddings)
- **Downloads**: slskd (Soulseek) with multi-strategy search + quality scoring
- **Discovery**: Last.fm API (similar tracks/artists, top charts, scrobbling)
- **Deployment**: Proxmox LXC via `create-ct.sh` interactive installer

## Commands
- Backend: `uv run uvicorn backend.main:app --reload --port 8000`
- Frontend dev: `cd frontend && npm run dev` (proxies /api and /rest to :8000)
- Worker: `uv run arq backend.workers.WorkerSettings` (requires Redis)
- Migrations: `uv run alembic upgrade head`
- New migration: `uv run alembic revision --autogenerate -m "description"`
- Verify loads: `uv run python -c "from backend.main import app; print('OK')"`
- SSH to Proxmox: `ssh root@pve5` (CT 228 on pve5)
- Upgrade production: `ssh root@pve5 "pct exec 228 -- bash -c 'cd /opt/zonik && bash upgrade.sh'"`

## Project Structure
```
backend/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Settings from zonik.toml (Pydantic models)
  database.py          # SQLAlchemy engine, FTS5 setup, search helpers
  models/              # 14 SQLAlchemy models (Track, Artist, Album, etc.)
  api/                 # REST API routes (tracks, library, download, discovery, config, etc.)
    config_api.py      # Services config + version/updates/upgrade endpoints
    jobs.py            # Job listing and details
    tracks.py          # Track CRUD + search
    library.py         # Library stats + scan trigger
    download.py        # Soulseek search/trigger/bulk + blacklist
    discovery.py       # Last.fm charts, similar tracks/artists
    analysis.py        # Essentia/CLAP analysis queue
    schedule.py        # Cron scheduler management
    websocket.py       # Real-time job progress
    favorites.py       # Star/unstar
    playlists.py       # Playlist CRUD
  subsonic/            # Full OpenSubsonic API (auth, browsing, media, search, etc.)
  services/            # Business logic (scanner, soulseek, lastfm, artwork, etc.)
  workers/             # ARQ task functions + cron scheduler
  migrations/          # Alembic migrations
frontend/
  src/routes/          # SvelteKit pages (12 routes)
    +page.svelte       # Dashboard (stats, recent additions)
    library/           # Track browser with search, sort, similar tracks
    discover/          # Last.fm charts, similar artists
    downloads/         # Soulseek download management
    playlists/         # Playlist management
    favorites/         # Starred items
    analysis/          # Audio analysis queue
    stats/             # Library statistics
    schedule/          # Cron job scheduler
    logs/              # Job history
    settings/          # Service config, subsonic info, updates/upgrade
  src/components/      # Sidebar (with update indicator), Player, Toast
    ui/                # 8 reusable components: Button, Badge, Card, Skeleton, FormInput, Modal, EmptyState, PageHeader
  src/lib/             # api.js, stores.js, utils.js, websocket.js
deploy/                # Systemd service files
docs/                  # Installation, configuration, API reference, development guide
```

## Key Design Decisions
- Track-focused (not album-focused) — download individual tracks, not discographies
- Track IDs = MD5 of relative file path (stable across scans)
- Artist/Album IDs = MD5 of normalized name key
- SQLite with FTS5 for search, populated during library scan
- All async (aiosqlite, httpx, arq)
- Subsonic auth via token or password; search3 empty query = Symfonium fast sync
- Stream transcoding via ffmpeg (maxBitRate, format, timeOffset)
- Download blacklist system (block artists or specific tracks)
- Cover art: Deezer > Cover Art Archive > iTunes > Last.fm fallback
- Soulseek search: 4-strategy fallback (full → cleaned → track-only → first-word)
- Soulseek retry with candidate fallback: search_and_download tries up to 5 candidates before failing
- Config: zonik.toml (gitignored), zonik.toml.example (committed with empty keys)
- Service connections (slskd, Lidarr, Last.fm) configurable via web UI Settings page
- Settings page: color-coded test buttons, per-field eye toggles for API keys
- Download dir and cover cache dir also web-configurable
- Installer (`create-ct.sh`) only asks for infrastructure — no API keys
- SPA routing: catch-all route serves index.html for client-side SvelteKit routes
- Web UI upgrade system: check GitHub for updates, run upgrade.sh as background Job with live progress
- Sidebar shows yellow pulsing dot on Settings when update is available
- upgrade.sh supports SKIP_RESTART=1 env var (used by web UI to handle restart separately)
- Backend sends full API keys (not masked) — self-hosted single-user app, frontend password fields handle hiding
- WebSocket real-time job progress (broadcast_job_update in download.py for single and bulk downloads)
- "Download All Missing" button on Discover page wires to /api/download/bulk
- Active jobs indicator in sidebar footer (spinning loader + count)

## Important Files
- `zonik.toml` — Local config with real API keys (NEVER commit)
- `zonik.toml.example` — Template with empty keys (safe to commit)
- `create-ct.sh` — Proxmox host installer (creates CT + installs app, no API key prompts)
- `install.sh` — In-CT installer (for existing Debian 12 containers)
- `upgrade.sh` — Pull, rebuild, restart (also triggered from web UI Settings page)
- `pyproject.toml` — Python package definition, version string read dynamically by backend

## Frontend Notes
- Svelte 5 runes: use `$state`, `$derived` (not `{@const}` outside control blocks)
- `package.json` requires `"type": "module"` for ESM
- `@sveltejs/vite-plugin-svelte` v5+ required for vite 6
- SPA: `adapter-static` with `fallback: 'index.html'`; backend has catch-all route
- Production URL: `http://10.0.0.205:3000` (CT 228)
- Svelte 5 deprecation warnings (on:click → onclick) are harmless, builds succeed
- `stores.js` exports: sidebarOpen, currentTrack, isPlaying, activeJobs, toasts, updateAvailable, addToast
- CSS variable-based design system in `app.css` (layered backgrounds: --bg-primary/#0a0a0a → --bg-secondary → --bg-tertiary → --bg-hover)
- Per-section color coding (dashboard=indigo, library=purple, discover=green, downloads=blue, playlists=amber, favorites=red, analysis=pink, stats=cyan, schedule=orange, logs=violet, settings=slate)
- Inter font via Google Fonts CDN; lucide-svelte icons throughout (tree-shakeable SVG icons)
- 8 reusable UI components in `frontend/src/components/ui/`: Button (6 variants), Badge (5 variants), Card, Skeleton, FormInput, Modal, EmptyState, PageHeader
- WebSocket connected in +layout.svelte on mount
- Default admin credentials: admin/admin (created on first startup)

## Infrastructure
- CT 228 on pve5 (Zonik production)
- CT 224 on pve5 (slskd — Soulseek client, `10.0.0.116:5030`)
- CT 210 (Lidarr, `10.0.0.179:8686`)
- CT 215 on pve4 (Kima-Hub, reference for mount points)
- Mount points: `/nfs/MUSIC` → `/music`, `/nfs/DOWNLOADS` → `/downloads`

## Workflow
- Dev machine: `/home/spider/zonik` (WSL2, no sudo, no Node.js globally)
- Git remote: `https://github.com/Pr0zak/Zonik.git` (user: Pr0zak)
- Typical flow: edit → verify loads → commit → push → upgrade CT 228
- Always verify backend loads before committing: `uv run python -c "from backend.main import app; print('OK')"`
- After push, upgrade production: SSH into pve5, run upgrade.sh on CT 228

## External Services
- slskd (Soulseek P2P): API at configured URL (set via web UI)
- Last.fm: Read API + Write API (scrobble, love) with method signatures (set via web UI)
- Lidarr: Secondary download source (set via web UI)
- MusicBrainz: Metadata enrichment
