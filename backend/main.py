from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import bcrypt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from backend.config import get_settings
from backend.database import async_session, init_db
from backend.models.user import User
from backend.api import tracks, library, favorites, playlists, jobs, download, discovery
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
    yield


settings = get_settings()

app = FastAPI(title="Zonik", version="0.1.0", lifespan=lifespan)

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

# Subsonic API
app.include_router(subsonic_router, prefix="/rest")

# Serve frontend build in production
frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    app.mount("/", StaticFiles(directory=str(frontend_build), html=True), name="frontend")
