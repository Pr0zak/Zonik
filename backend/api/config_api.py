"""Config API routes - read and update zonik.toml settings from the web UI."""
from __future__ import annotations

from pathlib import Path

import tomllib
from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import get_settings, CONFIG_PATHS

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
    lidarr_url: str = ""
    lidarr_api_key: str = ""
    lastfm_api_key: str = ""
    lastfm_write_api_key: str = ""
    lastfm_write_api_secret: str = ""


@router.get("/services")
async def get_service_config():
    """Get current service connection settings (keys are masked)."""
    settings = get_settings()
    return {
        "slskd_url": settings.soulseek.slskd_url,
        "slskd_api_key": _mask(settings.soulseek.slskd_api_key),
        "lidarr_url": settings.lidarr.url,
        "lidarr_api_key": _mask(settings.lidarr.api_key),
        "lastfm_api_key": _mask(settings.lastfm.api_key),
        "lastfm_write_api_key": _mask(settings.lastfm.write_api_key),
        "lastfm_write_api_secret": _mask(settings.lastfm.write_api_secret),
    }


@router.put("/services")
async def update_service_config(req: ServiceConfig):
    """Update service connection settings in zonik.toml."""
    raw = _read_raw_config()
    settings = get_settings()

    # Only update fields that were actually provided (non-empty)
    # For keys: if the value looks masked (ends with ***), keep the existing value
    soulseek = raw.get("soulseek", {})
    if req.slskd_url or req.slskd_url == "":
        soulseek["slskd_url"] = req.slskd_url
    if req.slskd_api_key and not req.slskd_api_key.endswith("***"):
        soulseek["slskd_api_key"] = req.slskd_api_key
    raw["soulseek"] = {**settings.soulseek.model_dump(), **soulseek}

    lidarr = raw.get("lidarr", {})
    if req.lidarr_url or req.lidarr_url == "":
        lidarr["url"] = req.lidarr_url
    if req.lidarr_api_key and not req.lidarr_api_key.endswith("***"):
        lidarr["api_key"] = req.lidarr_api_key
    raw["lidarr"] = {**settings.lidarr.model_dump(), **lidarr}

    lastfm = raw.get("lastfm", {})
    if req.lastfm_api_key and not req.lastfm_api_key.endswith("***"):
        lastfm["api_key"] = req.lastfm_api_key
    if req.lastfm_write_api_key and not req.lastfm_write_api_key.endswith("***"):
        lastfm["write_api_key"] = req.lastfm_write_api_key
    if req.lastfm_write_api_secret and not req.lastfm_write_api_secret.endswith("***"):
        lastfm["write_api_secret"] = req.lastfm_write_api_secret
    raw["lastfm"] = {**settings.lastfm.model_dump(), **lastfm}

    # Preserve other sections
    for section in ["server", "library", "database", "redis", "analysis", "subsonic"]:
        if section not in raw:
            raw[section] = getattr(settings, section).model_dump()

    _write_config(raw)
    return {"status": "ok"}


def _mask(value: str) -> str:
    """Mask an API key for display, showing only last 4 chars."""
    if not value or len(value) < 8:
        return value
    return value[:4] + "***" + value[-4:]
