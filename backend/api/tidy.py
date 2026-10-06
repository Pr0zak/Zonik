"""Library tidy API: build a dry-run plan of where every file should go, and page through it.

Moving files is not here yet; it comes as a journalled job (plans/library-tidy.md).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.services import tidy, tidy_backup

router = APIRouter()


@router.post("/plan")
async def start_plan():
    """Start building a plan in the background (reading every file's tags takes minutes)."""
    started = tidy.start()
    return {"started": started, **tidy.state}


@router.get("/status")
async def status():
    plan = tidy.load_plan()
    return {**tidy.state, "summary": plan["summary"] if plan else None}


@router.get("/plan")
async def get_plan(status: str | None = None, rule: str | None = None, q: str | None = None,
                   favorites: bool = False, offset: int = 0, limit: int = 200):
    """The last plan's moves, filtered: by status (move, unchanged, conflict, skip), by rule
    (album, single, compilation, untagged), by text in either path, or favorites only."""
    plan = tidy.load_plan()
    if not plan:
        return {"summary": None, "total": 0, "moves": []}
    moves = plan["moves"]
    if status:
        moves = [m for m in moves if m["status"] == status]
    if rule:
        moves = [m for m in moves if m["rule"] == rule]
    if favorites:
        moves = [m for m in moves if m["favorite"]]
    if q:
        ql = q.lower()
        moves = [m for m in moves if ql in m["from"].lower() or ql in m["to"].lower()]
    limit = max(1, min(limit, 1000))
    return {"summary": plan["summary"], "total": len(moves), "moves": moves[offset:offset + limit]}


@router.get("/settings")
async def get_settings_():
    from backend.services.tidy_rules import TidyOptions
    return {"settings": tidy.load_options().to_dict(), "defaults": TidyOptions().to_dict()}


@router.put("/settings")
async def put_settings(body: dict):
    """Merge the given settings; unknown keys and bad values fall back to defaults. Rebuild
    the plan afterwards to see their effect."""
    return {"settings": tidy.save_options(body.get("settings", body)).to_dict()}


@router.get("/backups")
async def backups():
    return {"backups": tidy_backup.list_backups(), "state": tidy_backup.state,
            "dir": str(tidy_backup.backups_dir())}


@router.post("/backups")
async def take_backup():
    name = tidy_backup.start()
    if name is None:
        raise HTTPException(409, "A backup is already running")
    return {"name": name, "state": tidy_backup.state}


@router.get("/backups/{name}/{filename}")
async def backup_file(name: str, filename: str):
    p = tidy_backup.file_path(name, filename)
    if p is None:
        raise HTTPException(404, "No such backup file")
    return FileResponse(p, filename=f"{name}-{filename}")
