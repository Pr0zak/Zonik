"""User management API routes."""
from __future__ import annotations

import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.get("")
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.username))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "is_admin": u.is_admin,
            "has_api_key": bool(u.subsonic_api_key),
            "subsonic_api_key": u.subsonic_api_key or "",
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("")
async def create_user(req: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username already exists")
    user = User(
        id=str(uuid.uuid4()),
        username=req.username,
        password_hash=bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode(),
        is_admin=req.is_admin,
    )
    db.add(user)
    await db.commit()
    return {"id": user.id, "username": user.username}


@router.put("/{user_id}/password")
async def change_password(user_id: str, req: PasswordChange, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if not bcrypt.checkpw(req.current_password.encode(), user.password_hash.encode()):
        raise HTTPException(403, "Current password is incorrect")
    user.password_hash = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    await db.commit()
    return {"ok": True}


@router.post("/{user_id}/api-key")
async def generate_api_key(user_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a new Subsonic API key for token-based auth (e.g. Symfonium)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.subsonic_api_key = secrets.token_hex(16)
    await db.commit()
    return {"ok": True, "api_key": user.subsonic_api_key}


@router.delete("/{user_id}/api-key")
async def revoke_api_key(user_id: str, db: AsyncSession = Depends(get_db)):
    """Revoke a user's Subsonic API key."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    user.subsonic_api_key = None
    await db.commit()
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    await db.delete(user)
    await db.commit()
    return {"ok": True}
