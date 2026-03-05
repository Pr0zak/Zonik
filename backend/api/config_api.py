"""Config API routes - read and update zonik.toml settings from the web UI."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import tomllib
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings, CONFIG_PATHS
from backend.database import get_db
from backend.models.job import Job

logger = logging.getLogger(__name__)

router = APIRouter()


def _find_config_path() -> Path:
    for p in CONFIG_PATHS:
        if p.exists():
            return p
    # Default to first path
    return CONFIG_PATHS[0]


def _read_raw_config() -> dict:
    path = _find_config_path()
    if path.exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


def _write_config(data: dict) -> None:
    """Write config dict back to zonik.toml."""
    path = _find_config_path()
    lines: list[str] = []

    def write_section(section: str, values: dict):
        lines.append(f"\n[{section}]")
        for k, v in values.items():
            if isinstance(v, bool):
                lines.append(f'{k} = {"true" if v else "false"}')
            elif isinstance(v, int):
                lines.append(f"{k} = {v}")
            elif isinstance(v, list):
                items = ", ".join(f'"{i}"' for i in v)
                lines.append(f"{k} = [{items}]")
            else:
                lines.append(f'{k} = "{v}"')

    for section, values in data.items():
        if isinstance(values, dict):
            write_section(section, values)

    path.write_text("\n".join(lines).strip() + "\n")

    # Clear cached settings so next get_settings() picks up changes
    get_settings.cache_clear()


class ServiceConfig(BaseModel):
    slskd_url: str = ""
    slskd_api_key: str = ""
    download_dir: str = ""
    lidarr_url: str = ""
    lidarr_api_key: str = ""
    lastfm_api_key: str = ""
    lastfm_write_api_key: str = ""
    lastfm_write_api_secret: str = ""
    cover_cache_dir: str = ""


@router.get("/services")
async def get_service_config():
    """Get current service connection settings."""
    settings = get_settings()
    return {
        "slskd_url": settings.soulseek.slskd_url,
        "slskd_api_key": settings.soulseek.slskd_api_key,
        "download_dir": settings.soulseek.download_dir,
        "lidarr_url": settings.lidarr.url,
        "lidarr_api_key": settings.lidarr.api_key,
        "lastfm_api_key": settings.lastfm.api_key,
        "lastfm_write_api_key": settings.lastfm.write_api_key,
        "lastfm_write_api_secret": settings.lastfm.write_api_secret,
        "cover_cache_dir": settings.library.cover_cache_dir,
    }


@router.put("/services")
async def update_service_config(req: ServiceConfig):
    """Update service connection settings in zonik.toml."""
    raw = _read_raw_config()
    settings = get_settings()

    # Update fields — full keys are sent from frontend, just save them
    soulseek = raw.get("soulseek", {})
    soulseek["slskd_url"] = req.slskd_url
    if req.slskd_api_key:
        soulseek["slskd_api_key"] = req.slskd_api_key
    if req.download_dir:
        soulseek["download_dir"] = req.download_dir
    raw["soulseek"] = {**settings.soulseek.model_dump(), **soulseek}

    lidarr = raw.get("lidarr", {})
    lidarr["url"] = req.lidarr_url
    if req.lidarr_api_key:
        lidarr["api_key"] = req.lidarr_api_key
    raw["lidarr"] = {**settings.lidarr.model_dump(), **lidarr}

    lastfm = raw.get("lastfm", {})
    if req.lastfm_api_key:
        lastfm["api_key"] = req.lastfm_api_key
    if req.lastfm_write_api_key:
        lastfm["write_api_key"] = req.lastfm_write_api_key
    if req.lastfm_write_api_secret:
        lastfm["write_api_secret"] = req.lastfm_write_api_secret
    raw["lastfm"] = {**settings.lastfm.model_dump(), **lastfm}

    # Update cover cache dir in library section
    library = raw.get("library", {})
    if req.cover_cache_dir:
        library["cover_cache_dir"] = req.cover_cache_dir
    raw["library"] = {**settings.library.model_dump(), **library}

    # Preserve other sections
    for section in ["server", "database", "redis", "analysis", "subsonic"]:
        if section not in raw:
            raw[section] = getattr(settings, section).model_dump()

    _write_config(raw)
    return {"status": "ok"}


@router.post("/test/{service}")
async def test_service(service: str):
    """Test connectivity to a configured service."""
    settings = get_settings()

    if service == "lastfm":
        api_key = settings.lastfm.api_key
        if not api_key:
            return {"status": "error", "message": "No API key configured"}
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://ws.audioscrobbler.com/2.0/", params={
                    "method": "chart.gettopartists",
                    "api_key": api_key,
                    "format": "json",
                    "limit": 1,
                })
                data = resp.json()
                if "error" in data:
                    return {"status": "error", "message": data.get("message", "Invalid API key")}
                return {"status": "ok", "message": "Connected"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif service == "soulseek":
        url = settings.soulseek.slskd_url
        key = settings.soulseek.slskd_api_key
        if not url:
            return {"status": "error", "message": "No slskd URL configured"}
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url.rstrip('/')}/api/v0/application", headers={"X-API-Key": key})
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connected"}
                elif resp.status_code == 401:
                    return {"status": "error", "message": "Invalid API key"}
                else:
                    return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif service == "lidarr":
        url = settings.lidarr.url
        key = settings.lidarr.api_key
        if not url:
            return {"status": "error", "message": "No Lidarr URL configured"}
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url.rstrip('/')}/api/v1/system/status", headers={"X-Api-Key": key})
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Connected"}
                elif resp.status_code == 401:
                    return {"status": "error", "message": "Invalid API key"}
                else:
                    return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": f"Unknown service: {service}"}


# --- Version / Update / Upgrade endpoints ---

_update_cache: dict = {}
CACHE_TTL = 300  # 5 minutes


def _get_version() -> str:
    """Get version from pyproject.toml."""
    pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("version", "unknown")
    return "unknown"


async def _get_local_commit() -> str:
    """Get current git commit hash."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--short", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if proc.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


async def _get_local_full_commit() -> str:
    """Get current git full commit hash."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


async def _fetch_remote_info() -> dict:
    """Fetch latest commit info from GitHub, with caching."""
    now = time.time()
    if _update_cache.get("data") and now - _update_cache.get("ts", 0) < CACHE_TTL:
        return _update_cache["data"]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.github.com/repos/Pr0zak/Zonik/commits/main",
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "sha": data["sha"],
                    "short_sha": data["sha"][:7],
                    "message": data["commit"]["message"].split("\n")[0],
                    "date": data["commit"]["committer"]["date"],
                    "author": data["commit"]["author"]["name"],
                }
                _update_cache["data"] = result
                _update_cache["ts"] = now
                return result
            return {"error": f"GitHub API returned {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/version")
async def get_version():
    """Get current version and commit info."""
    version = _get_version()
    commit = await _get_local_commit()
    return {"version": version, "commit": commit}


@router.get("/updates")
async def check_updates():
    """Check for available updates by comparing local HEAD with remote."""
    local_full = await _get_local_full_commit()
    local_short = await _get_local_commit()
    remote = await _fetch_remote_info()

    if "error" in remote:
        return {
            "update_available": False,
            "error": remote["error"],
            "current_commit": local_short,
        }

    update_available = local_full != remote["sha"]

    result = {
        "update_available": update_available,
        "current_commit": local_short,
        "latest_commit": remote["short_sha"],
        "latest_message": remote["message"],
        "latest_date": remote["date"],
        "latest_author": remote["author"],
    }

    # If update available, try to get commit list between local and remote
    if update_available:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/Pr0zak/Zonik/compare/{local_full}...{remote['sha']}",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result["commits"] = [
                        {
                            "sha": c["sha"][:7],
                            "message": c["commit"]["message"].split("\n")[0],
                            "author": c["commit"]["author"]["name"],
                        }
                        for c in data.get("commits", [])[:20]
                    ]
                    result["ahead_by"] = data.get("ahead_by", 0)
        except Exception:
            pass

    return result


async def _run_upgrade(job_id: str):
    """Run upgrade.sh in background and update the Job record."""
    from backend.database import async_session

    upgrade_script = Path(__file__).parent.parent.parent / "upgrade.sh"
    if not upgrade_script.exists():
        async with async_session() as session:
            result = await session.get(Job, job_id)
            if result:
                result.status = "failed"
                result.log = json.dumps(["Error: upgrade.sh not found"])
                result.finished_at = datetime.now(timezone.utc)
                await session.commit()
        return

    log_lines: list[str] = []
    step = 0

    try:
        # Run upgrade steps 1-4 (everything except service restart).
        # We skip step 5 (systemctl restart) because it kills this process.
        # Instead we mark the job completed and let the frontend reload.
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c",
            f"export SKIP_RESTART=1; source {upgrade_script}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**__import__("os").environ, "SKIP_RESTART": "1"},
        )

        async for line_bytes in proc.stdout:
            line = line_bytes.decode().rstrip()
            log_lines.append(line)

            # Track progress by detecting step markers
            if line.startswith("[") and "/5]" in line:
                try:
                    step = int(line[1])
                except (ValueError, IndexError):
                    pass

            # Update job periodically
            async with async_session() as session:
                job = await session.get(Job, job_id)
                if job:
                    job.progress = step
                    job.log = json.dumps(log_lines[-100:])  # Keep last 100 lines
                    await session.commit()

        await proc.wait()

        if proc.returncode == 0:
            # Mark completed before restart
            log_lines.append("[5/5] Restarting services...")
            async with async_session() as session:
                job = await session.get(Job, job_id)
                if job:
                    job.status = "completed"
                    job.progress = 5
                    job.log = json.dumps(log_lines)
                    job.finished_at = datetime.now(timezone.utc)
                    await session.commit()

            # Now restart services — this will kill us, but the job is already saved
            await asyncio.sleep(1)  # Give the DB write time to flush
            asyncio.create_task(_restart_services())
        else:
            async with async_session() as session:
                job = await session.get(Job, job_id)
                if job:
                    job.status = "failed"
                    job.progress = step
                    job.log = json.dumps(log_lines)
                    job.finished_at = datetime.now(timezone.utc)
                    await session.commit()

    except Exception as e:
        log_lines.append(f"Error: {e}")
        async with async_session() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status = "failed"
                job.log = json.dumps(log_lines)
                job.finished_at = datetime.now(timezone.utc)
                await session.commit()


async def _restart_services():
    """Restart systemd services after a short delay."""
    await asyncio.sleep(2)
    await asyncio.create_subprocess_exec(
        "systemctl", "restart", "zonik-web", "zonik-worker",
    )


@router.post("/upgrade")
async def trigger_upgrade(db: AsyncSession = Depends(get_db)):
    """Trigger an upgrade by running upgrade.sh in the background."""
    # Check if an upgrade is already running
    from sqlalchemy import select
    existing = await db.execute(
        select(Job).where(Job.type == "upgrade", Job.status.in_(["pending", "running"]))
    )
    if existing.scalar_one_or_none():
        return {"error": "An upgrade is already in progress"}

    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id,
        type="upgrade",
        card="System Upgrade",
        status="running",
        progress=0,
        total=5,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()

    # Run upgrade in background
    asyncio.create_task(_run_upgrade(job_id))

    return {"job_id": job_id}


def _mask(value: str) -> str:
    """Mask an API key for display, showing only last 4 chars."""
    if not value or len(value) < 8:
        return value
    return value[:4] + "***" + value[-4:]
