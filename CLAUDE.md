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
- SSH to Proxmox: `ssh -i ~/.ssh/proxmox_key root@pve5` (CT 228 on pve5)

## Project Structure
```
backend/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Settings from zonik.toml (Pydantic models)
  database.py          # SQLAlchemy engine, FTS5 setup, search helpers
  models/              # 14 SQLAlchemy models (Track, Artist, Album, etc.)
  api/                 # REST API routes (tracks, library, download, discovery, config, etc.)
    config_api.py      # Services config + version/updates/upgrade endpoints
  subsonic/            # Full OpenSubsonic API (auth, browsing, media, search, etc.)
  services/            # Business logic (scanner, soulseek, lastfm, artwork, etc.)
  workers/             # ARQ task functions + cron scheduler
  migrations/          # Alembic migrations
frontend/
  src/routes/          # SvelteKit pages (dashboard, library, discover, downloads, stats, etc.)
  src/components/      # Sidebar, Player, Toast
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
- Config: zonik.toml (gitignored), zonik.toml.example (committed with empty keys)
- Service connections (slskd, Lidarr, Last.fm) configurable via web UI Settings page
- Settings page has color-coded test buttons (green/red/yellow) for each service
- Download dir and cover cache dir also web-configurable
- Installer (`create-ct.sh`) only asks for infrastructure — no API keys
- SPA routing: catch-all route serves index.html for client-side SvelteKit routes
- Web UI upgrade system: check GitHub for updates, run upgrade.sh as background Job with live progress

## Important Files
- `zonik.toml` — Local config with real API keys (NEVER commit)
- `zonik.toml.example` — Template with empty keys (safe to commit)
- `create-ct.sh` — Proxmox host installer (creates CT + installs app, no API key prompts)
- `install.sh` — In-CT installer (for existing Debian 12 containers)
- `upgrade.sh` — Pull, rebuild, restart (also triggered from web UI Settings page)

## Frontend Notes
- Svelte 5 runes: use `$state`, `$derived` (not `{@const}` outside control blocks)
- `package.json` requires `"type": "module"` for ESM
- `@sveltejs/vite-plugin-svelte` v5+ required for vite 6
- SPA: `adapter-static` with `fallback: 'index.html'`; backend has catch-all route
- Production URL: `http://10.0.0.205:3000` (CT 228)

## Infrastructure
- CT 228 on pve5 (Zonik production)
- CT 215 on pve4 (Kima-Hub, reference for mount points)
- Mount points: `/nfs/MUSIC` → `/music`, `/nfs/DOWNLOADS` → `/downloads`

## External Services
- slskd (Soulseek P2P): API at configured URL (set via web UI)
- Last.fm: Read API + Write API (scrobble, love) with method signatures (set via web UI)
- Lidarr: Secondary download source (set via web UI)
- MusicBrainz: Metadata enrichment
