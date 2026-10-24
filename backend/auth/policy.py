"""Path policy: the permission each /api request needs.

An ordered list of (methods, path regex, perm); the first rule whose methods (None = any)
and regex match wins. Regexes are matched against the request path and are written with
[^/]+ for path parameters, so they match route templates (/api/tracks/{track_id}) too —
tests/test_auth.py walks app.routes through perm_for() to prove every route resolves.

No rule matched: GET/HEAD need library.read, any other method is admin-only (ADMIN_DEFAULT).
PUBLIC routes skip authentication entirely.
"""
from __future__ import annotations

import re

PUBLIC = "public"
ADMIN_DEFAULT = "library.manage"

_ANY = None
_GET = frozenset({"GET", "HEAD"})
_POST = frozenset({"POST"})
_PUT = frozenset({"PUT"})
_DELETE = frozenset({"DELETE"})

_ID = r"[^/]+"

_RAW_RULES: list[tuple[frozenset | None, str, str]] = [
    # --- public: never authenticated --------------------------------------------------
    (_GET, r"/api/health", PUBLIC),
    (_ANY, r"/api/auth/(status|login|setup|device|logout)", PUBLIC),
    (_POST, r"/api/logs", PUBLIC),  # phone log upload, permissive as before
    (_ANY, r"/api/pair(/.*)?", PUBLIC),

    # --- admin-only whatever the method ---------------------------------------------
    (_ANY, r"/api/users(/.*)?", "users.manage"),
    (_ANY, r"/api/tidy(/.*)?", "library.manage"),
    (_ANY, r"/api/upgrades(/.*)?", "library.manage"),
    (_ANY, r"/api/library/upgrades(/.*)?", "library.manage"),
    (_ANY, r"/api/schedule(/.*)?", "settings.manage"),
    (_ANY, r"/api/logs/app(/.*)?", "logs.read"),
    (_ANY, r"/api/ai-usage(/.*)?", "settings.manage"),
    (_ANY, r"/api/download/blacklist(/.*)?", "downloads.admin"),
    (_ANY, r"/api/library/(scan|cleanup(/.*)?|duplicates(/.*)?)", "library.manage"),
    (_ANY, r"/api/discovery/lastfm/.*", "settings.manage"),  # connects the Last.fm account
    (_ANY, r"/api/map/soundscape/recompute", "library.manage"),
    # Config: user-safe reads first, everything else (third-party API keys, restart,
    # upgrade, backups, Soulseek settings) is admin.
    # Shuffle Mix tuning is server-wide (the GET's never_played/in_cooldown are per caller).
    (_GET, r"/api/config/shuffle", "library.read"),
    (_PUT, r"/api/config/shuffle", "settings.manage"),
    (_GET, r"/api/config/(version|updates)", "library.read"),
    (_ANY, r"/api/config(/.*)?", "settings.manage"),
    # Track edits/deletes and bulk tag/analysis jobs.
    (_ANY, rf"/api/tracks/(bulk-delete|bulk-analyze|ai-tag(/apply)?|ai-moods|repair-tags)", "library.manage"),
    (_POST, rf"/api/tracks/{_ID}/play", "play"),
    (_PUT, rf"/api/tracks/{_ID}/rating", "own.write"),
    (frozenset({"PUT", "DELETE"}), rf"/api/tracks/{_ID}", "library.manage"),

    # --- user-allowed writes ----------------------------------------------------------
    (_ANY, r"/api/favorites(/.*)?", "own.write"),
    (_ANY, r"/api/playlists(/.*)?", "own.write"),  # owner-only edits enforced in the playlist routes
    (_POST, rf"/api/recommendations/(refresh|feedback|{_ID}/explain)", "own.write"),
    (_POST, r"/api/recommendations/bulk-download", "downloads.use"),
    (_POST, rf"/api/live/skips/{_ID}/reset", "own.write"),
    (_ANY, r"/api/assistant(/.*)?", "play"),
    (_ANY, r"/api/search(/.*)?", "library.read"),  # AI search, NL detect, catalog
    (_POST, r"/api/discovery/(artwork/batch|playlists|playlists/ai-rank)", "library.read"),
    (_POST, r"/api/analysis/(echo-match|vibe-search|steady-vibes)", "library.read"),
    (_POST, r"/api/map/gems/dismiss", "own.write"),
    (_POST, r"/api/map/(sonic-path|soundscape/locate)", "library.read"),
    (_ANY, r"/api/download/(trigger|search|bulk|status|cancel-transfer)", "downloads.use"),
    (_GET, r"/api/jobs(/.*)?", "downloads.use"),
    (_GET, r"/api/tv/visualizer/.*", "library.read"),
    (_POST, r"/api/tv/visualizer/stats", "play"),
    (_ANY, r"/api/auth/.*", "own.write"),  # me, password, devices: the caller's own account
]

RULES: list[tuple[frozenset | None, re.Pattern, str]] = [
    (methods, re.compile(f"^{pattern}$"), perm) for methods, pattern, perm in _RAW_RULES
]


def perm_for(method: str, path: str) -> str:
    """Permission (or PUBLIC) a request needs."""
    method = method.upper()
    path = path.rstrip("/") or "/"
    for methods, regex, perm in RULES:
        if (methods is None or method in methods) and regex.match(path):
            return perm
    return "library.read" if method in _GET else ADMIN_DEFAULT
