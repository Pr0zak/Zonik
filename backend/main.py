from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import bcrypt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.api.config_api import _get_version
from backend.config import get_settings
from backend.database import async_session, init_db
from backend.models.user import User
from backend.models.job import Job
from backend.api import tracks, library, favorites, playlists, jobs, download, discovery, analysis, schedule, websocket, config_api, users
from backend.subsonic import router as subsonic_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Ensure default admin user exists
    async with async_session() as session:
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none() is None:
            user = User(
                id=str(uuid.uuid4()),
                username="admin",
                password_hash=bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode(),
                is_admin=True,
            )
            session.add(user)
            await session.commit()

    # Mark any stuck "running" jobs as failed (killed by restart)
    log = logging.getLogger(__name__)
    async with async_session() as session:
        from sqlalchemy import update
        from datetime import datetime
        stuck = await session.execute(
            update(Job)
            .where(Job.status.in_(["running", "pending"]))
            .values(status="failed", finished_at=datetime.utcnow())
        )
        if stuck.rowcount:
            await session.commit()
            log.info(f"Marked {stuck.rowcount} stuck jobs as failed on startup")
    if settings.soulseek.username:
        try:
            from backend.soulseek import start_client
            await start_client()
        except Exception as e:
            log.error(f"Failed to start native Soulseek client: {e}")

    yield

    # Stop native Soulseek client
    try:
        from backend.soulseek import stop_client
        await stop_client()
    except Exception as e:
        log.debug("Soulseek client shutdown error: %s", e)


settings = get_settings()

app = FastAPI(title="Zonik", version=_get_version(), lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(tracks.router, prefix="/api/tracks", tags=["tracks"])
app.include_router(library.router, prefix="/api/library", tags=["library"])
app.include_router(favorites.router, prefix="/api/favorites", tags=["favorites"])
app.include_router(playlists.router, prefix="/api/playlists", tags=["playlists"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(download.router, prefix="/api/download", tags=["download"])
app.include_router(discovery.router, prefix="/api/discovery", tags=["discovery"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(schedule.router, prefix="/api/schedule", tags=["schedule"])
app.include_router(config_api.router, prefix="/api/config", tags=["config"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(websocket.router, prefix="/api", tags=["websocket"])

# Subsonic API
app.include_router(subsonic_router, prefix="/rest")

# Serve frontend build in production
frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    from fastapi.responses import FileResponse

    app.mount("/_app", StaticFiles(directory=str(frontend_build / "_app")), name="frontend-assets")
    app.mount("/static", StaticFiles(directory=str(frontend_build)), name="frontend-static")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve SvelteKit SPA — return index.html for all non-API routes."""
        file = frontend_build / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(frontend_build / "index.html")
