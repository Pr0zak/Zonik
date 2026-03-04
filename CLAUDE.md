# Zonik

Self-hosted music backend serving Symfonium via OpenSubsonic API.

## Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 async + SQLite (WAL+FTS5) + ARQ/Redis
- **Frontend**: SvelteKit 5 + Tailwind CSS (dark theme, 11 routes)
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

## Project Structure
```
backend/
  main.py              # FastAPI app, lifespan, router registration
  config.py            # Settings from zonik.toml (Pydantic models)
  database.py          # SQLAlchemy engine, FTS5 setup, search helpers
  models/              # 14 SQLAlchemy models (Track, Artist, Album, etc.)
  api/                 # REST API routes (tracks, library, download, discovery, etc.)
  subsonic/            # Full OpenSubsonic API (auth, browsing, media, search, etc.)
  services/            # Business logic (scanner, soulseek, lastfm, artwork, etc.)
  workers/             # ARQ task functions + cron scheduler
  migrations/          # Alembic migrations
frontend/
  src/routes/          # SvelteKit pages (dashboard, library, discover, downloads, etc.)
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

## Important Files
- `zonik.toml` — Local config with real API keys (NEVER commit)
- `zonik.toml.example` — Template with empty keys (safe to commit)
- `create-ct.sh` — Proxmox host installer (creates CT + installs app)
- `install.sh` — In-CT installer (for existing Debian 12 containers)
- `upgrade.sh` — Pull, rebuild, restart

## External Services
- slskd (Soulseek P2P): API at configured URL
- Last.fm: Read API + Write API (scrobble, love) with method signatures
- Lidarr: Secondary download source
- MusicBrainz: Metadata enrichment
