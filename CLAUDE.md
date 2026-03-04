# Zonik

Self-hosted music backend serving Symfonium via OpenSubsonic API.

## Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 async + SQLite (WAL) + ARQ/Redis
- **Frontend**: SvelteKit + Tailwind CSS
- **Audio**: mutagen (tags), Essentia (analysis), CLAP (embeddings)

## Commands
- Backend: `cd /home/spider/zonik && uv run uvicorn backend.main:app --reload --port 8000`
- Frontend dev: `cd /home/spider/zonik/frontend && npm run dev`
- Migrations: `cd /home/spider/zonik && uv run alembic upgrade head`
- New migration: `cd /home/spider/zonik && uv run alembic revision --autogenerate -m "description"`

## Project Structure
- `backend/` - FastAPI app, models, services, workers
- `backend/subsonic/` - OpenSubsonic API for Symfonium
- `backend/api/` - Web UI REST API
- `backend/services/` - Business logic (scanner, tagger, soulseek, etc.)
- `frontend/` - SvelteKit SPA

## Key Design Decisions
- Track-focused (not album-focused like Kima-Hub)
- SQLite with FTS5 for search + sqlite-vec for embeddings
- All async (aiosqlite, httpx, arq)
- Subsonic auth via token or password
