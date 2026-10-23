"""bcrypt helpers shared by login, setup and the users API."""
from __future__ import annotations

import bcrypt

MIN_PASSWORD_LENGTH = 8
# The password the old bootstrap created. A user still on it is asked for a new one.
DEFAULT_PASSWORD = "admin"

# password_hash -> "is the password literally 'admin'". bcrypt costs ~0.2 s, and /me is read
# on every page load; a hash only ever answers one way, so the result never goes stale.
_default_password_cache: dict[str, bool] = {}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str | None) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # not a bcrypt hash
        return False


def must_change_password(password_hash: str | None) -> bool:
    if not password_hash:
        return False
    cached = _default_password_cache.get(password_hash)
    if cached is None:
        cached = check_password(DEFAULT_PASSWORD, password_hash)
        if len(_default_password_cache) > 1000:
            _default_password_cache.clear()
        _default_password_cache[password_hash] = cached
    return cached


def new_password_problem(password: str) -> str | None:
    """Why a new password is refused, or None when it's acceptable."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if password == DEFAULT_PASSWORD:
        return "Choose a password other than 'admin'"
    return None
