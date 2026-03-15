# Zonik

Self-hosted music backend serving Symfonium via OpenSubsonic API.

## Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 async + SQLite (WAL+FTS5) or PostgreSQL + ARQ/Redis
- **Frontend**: SvelteKit 5 + Tailwind CSS + Chart.js + D3.js (dark theme, 15 routes)
- **Audio**: mutagen (tags), Essentia (analysis), CLAP (vibe embeddings)
- **Downloads**: Native Soulseek P2P client (or legacy slskd) with multi-strategy search + quality scoring
- **Discovery**: Last.fm API (similar tracks/artists, top charts, scrobbling)
- **AI**: Claude API via shared client (backend/services/ai/), 10 toggleable features
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
  database.py          # SQLAlchemy engine, FTS5/tsvector setup, search helpers
  database_compat.py   # Dialect-aware SQL helpers (SQLite + PostgreSQL)
  models/              # 18 SQLAlchemy models
  api/                 # REST API routes (~15 modules)
  subsonic/            # Full OpenSubsonic API
  soulseek/            # Native Soulseek P2P client (protocol, network, transfers)
  services/            # Business logic (scanner, soulseek, lastfm, cleanup, recommender, etc.)
    ai/                # AI feature modules (client.py + 9 feature modules)
  middleware/          # Rate limiting (token bucket, per-IP)
  workers/             # ARQ task functions + cron scheduler
  migrations/          # Alembic migrations
frontend/
  src/routes/          # SvelteKit pages (15 routes)
  src/components/      # Sidebar, TopBar, Player, Toast
    ui/                # 11 reusable components (Button, Badge, Card, Modal, etc.)
  src/lib/             # api.js, stores.js, utils.js, websocket.js, schedule.js, colors.js
deploy/                # Systemd service files
```

## Key Design Decisions
- Track IDs = MD5 of relative file path; Artist/Album IDs = MD5 of normalized name
- SQLite with NullPool (no connection pooling) — PRAGMAs set via connect event listener
- Subsonic auth: apiKey param, token+salt (md5), or password (plain/enc:hex)
- Subsonic compat: coverArt=entity ID, isDir/isVideo=boolean, bpm=int, artist/album always present
- Config: zonik.toml (gitignored), zonik.toml.example (committed)
- SPA routing: catch-all route serves index.html for client-side SvelteKit
- Default admin: admin/admin (created on first startup)

## Critical Pitfalls
- **SQLite single-writer**: never hold async_session() during long ops (semaphore waits, downloads); use short-lived sessions + expunge()
- **AsyncSession**: `exec_driver_sql` is NOT on AsyncSession — use `db.execute(text("..."))` instead
- **Track deletion**: must delete from all 8 FK tables before Track (Favorite, TrackAnalysis, TrackEmbedding, PlayHistory, PlaylistTrack, Bookmark, TrackMood, TrackUpgrade) + FTS
- **Track model**: NO `bpm` column — BPM is on TrackAnalysis (requires outerjoin); uses `duration_seconds` not `duration`
- **Svelte 5**: `{@const}` must be direct child of {#each}/{#if}, NOT inside component children
- **BrokenProcessPool**: import from `concurrent.futures.process` (NOT top-level concurrent.futures)
- **Essentia**: .opus needs ffmpeg pre-conversion; >2 channels must be skipped
- **Upgrade track swap**: raw SQL with PRAGMA foreign_keys=OFF (ORM cascade breaks TrackAnalysis PK)
- **Rate limiter**: excludes /api/download/ and /rest/ paths
- **Sort security**: allowlist sets prevent arbitrary getattr() on model attributes
- **URLSearchParams**: filter out undefined/null values (converts to literal "undefined")

## Important Files
- `zonik.toml` — Local config with real API keys (NEVER commit)
- `zonik.toml.example` — Template with empty keys (safe to commit)
- `create-ct.sh` / `install.sh` / `upgrade.sh` — Deployment scripts

## Infrastructure
- CT 228 on pve5 (production, port 3000, venv at /opt/zonik/venv/)
- Mounts: `/nfs/MUSIC` → `/music`, `/nfs/DOWNLOADS` → `/downloads`

## Workflow
- Dev: `/home/spider/zonik` (WSL2, no sudo, no global Node.js)
- Git remote: `https://github.com/Pr0zak/Zonik.git` (user: Pr0zak)
- Flow: edit → verify → commit → push → upgrade CT 228
- Verify-loads fails on WSL2 (no /opt/zonik/data) — use syntax check instead

## Frontend Notes
- Svelte 5 runes: `$state`, `$derived` (deprecation warnings are harmless)
- SPA: `adapter-static` with `fallback: 'index.html'`
- CSS variables in app.css (--bg-primary, --bg-secondary, etc.)
- Inter font via Google Fonts; lucide-svelte icons
- WebSocket connected in +layout.svelte on mount
