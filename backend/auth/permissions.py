"""Roles and permissions. One table in code; the path policy (policy.py) maps routes to these."""
from __future__ import annotations

from fastapi import HTTPException, Request

# What a regular user may do: browse, play, manage their own things, request downloads.
USER_PERMS = frozenset({"library.read", "play", "own.write", "downloads.use"})
# Admin-only: download/Soulseek management, library changes, settings, users, logs.
ADMIN_ONLY_PERMS = frozenset({"downloads.admin", "library.manage", "settings.manage", "users.manage", "logs.read"})
ALL_PERMS = USER_PERMS | ADMIN_ONLY_PERMS

ROLE_PERMS = {
    "admin": ALL_PERMS,
    "user": USER_PERMS,
}


def permissions_for(user) -> list[str]:
    if user is None or getattr(user, "disabled", False):
        return []
    return sorted(ROLE_PERMS.get(getattr(user, "role", None) or "user", USER_PERMS))


def has_perm(user, perm: str) -> bool:
    if user is None or getattr(user, "disabled", False):
        return False
    return perm in ROLE_PERMS.get(getattr(user, "role", None) or "user", USER_PERMS)


def require(perm: str):
    """Route dependency for checks finer than the path policy. The /api gate has already
    resolved request.state.user (the owner in grace mode)."""
    async def _check(request: Request) -> None:
        user = getattr(request.state, "user", None)
        if user is not None and not has_perm(user, perm):
            raise HTTPException(403, "Admins only")
    return _check
