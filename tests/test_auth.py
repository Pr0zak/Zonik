"""P1 auth foundation: login/sessions, setup, lockout, grace vs enforce on /api, /rest and
/api/ws, roles + the path policy, device tokens, Subsonic params on /api, disabled users,
last-admin guards and the CSRF origin check.

Requests go through the real app (httpx ASGITransport, no lifespan) so the /api gate, the
/rest gate and the exception handler are exercised exactly as deployed.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_auth.py
"""
import hashlib
import inspect
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from sqlalchemy import select

from backend.auth import lockout
from backend.auth.passwords import hash_password
from backend.auth.permissions import ALL_PERMS
from backend.auth.policy import PUBLIC, perm_for
from backend.auth.resolve import api_gate, reset_grace_log
from backend.config import get_settings
from backend.database import async_session
from backend.main import app
from backend.middleware.rate_limit import RateLimiter
from backend.models.auth import AuthSession, DeviceToken
from backend.models.user import User

API_KEY = "0123456789abcdef0123456789abcdef"
PASSWORD = "correct horse"

# The rate limiter would 429 a test module's burst of requests from one client address.
app.user_middleware = [m for m in app.user_middleware if m.cls is not RateLimiter]
app.middleware_stack = None


@pytest_asyncio.fixture
async def env(db_ready, monkeypatch):
    lockout.reset_all()
    reset_grace_log()
    monkeypatch.setattr(get_settings().auth, "enforce", False)
    yield
    lockout.reset_all()


def client(addr: str = "10.0.0.50") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(addr, 5555)),
                             base_url="http://testserver")


def enforce(monkeypatch, on: bool = True):
    monkeypatch.setattr(get_settings().auth, "enforce", on)


async def add_user(username="admin", password=PASSWORD, role="admin", api_key=API_KEY, disabled=False) -> User:
    async with async_session() as db:
        user = User(id=str(uuid.uuid4()), username=username, password_hash=hash_password(password),
                    subsonic_api_key=api_key, role=role, disabled=disabled)
        db.add(user)
        await db.commit()
        return user


def subsonic_params(username="admin", key=API_KEY, salt="s4lt") -> dict:
    return {"u": username, "t": hashlib.md5((key + salt).encode()).hexdigest(), "s": salt,
            "c": "test", "v": "1.16.1", "f": "json"}


async def login(c: httpx.AsyncClient, username="admin", password=PASSWORD) -> httpx.Response:
    return await c.post("/api/auth/login", json={"username": username, "password": password})


# --- policy ---------------------------------------------------------------------------

def _api_routes():
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api"):
            yield route


def test_policy_covers_every_api_route():
    table = []
    for route in _api_routes():
        for method in sorted(route.methods):
            perm = perm_for(method, route.path)
            assert perm == PUBLIC or perm in ALL_PERMS, (method, route.path, perm)
            table.append(f"{perm:16} {method:6} {route.path}")
    assert len(table) > 150
    print("\n" + "\n".join(sorted(table)))


def test_every_api_route_is_behind_the_gate():
    for route in _api_routes():
        calls = [d.call for d in route.dependant.dependencies]
        assert api_gate in calls, route.path


@pytest.mark.parametrize("method,path,perm", [
    ("GET", "/api/auth/status", PUBLIC),
    ("POST", "/api/auth/login", PUBLIC),
    ("POST", "/api/auth/logout", PUBLIC),
    ("POST", "/api/logs", PUBLIC),
    ("POST", "/api/pair", PUBLIC),
    ("POST", "/api/pair/123456/submit", PUBLIC),
    ("GET", "/api/auth/me", "own.write"),
    ("GET", "/api/logs/app", "logs.read"),
    ("DELETE", "/api/logs/app/abc", "logs.read"),
    ("GET", "/api/users", "users.manage"),
    ("GET", "/api/config/services", "settings.manage"),
    ("GET", "/api/config/shuffle", "own.write"),
    ("PUT", "/api/config/shuffle", "own.write"),
    ("GET", "/api/config/version", "library.read"),
    ("GET", "/api/config/updates", "library.read"),
    ("POST", "/api/config/restart", "settings.manage"),
    ("GET", "/api/tidy/status", "library.manage"),
    ("GET", "/api/upgrades", "library.manage"),
    ("GET", "/api/schedule", "settings.manage"),
    ("GET", "/api/ai-usage/dashboard", "settings.manage"),
    ("GET", "/api/download/blacklist", "downloads.admin"),
    ("POST", "/api/download/trigger", "downloads.use"),
    ("POST", "/api/download/bulk", "downloads.use"),
    ("GET", "/api/download/status", "downloads.use"),
    ("POST", "/api/download/reset-reputation", "library.manage"),
    ("GET", "/api/jobs", "downloads.use"),
    ("GET", "/api/jobs/abc", "downloads.use"),
    ("DELETE", "/api/jobs/clear", "library.manage"),
    ("POST", "/api/jobs/retry-failed", "library.manage"),
    ("POST", "/api/library/scan", "library.manage"),
    ("GET", "/api/library/duplicates", "library.manage"),
    ("GET", "/api/library/stats", "library.read"),
    ("POST", "/api/tracks/abc/play", "play"),
    ("PUT", "/api/tracks/abc", "library.manage"),
    ("DELETE", "/api/tracks/abc", "library.manage"),
    ("POST", "/api/tracks/bulk-delete", "library.manage"),
    ("POST", "/api/favorites/star", "own.write"),
    ("DELETE", "/api/playlists/abc", "own.write"),
    ("POST", "/api/playlists/import/fetch", "own.write"),
    ("POST", "/api/recommendations/refresh", "own.write"),
    ("POST", "/api/recommendations/bulk-download", "library.manage"),
    ("POST", "/api/assistant/voice-playlist", "play"),
    ("POST", "/api/search/ai", "library.read"),
    ("GET", "/api/search/catalog", "library.read"),
    ("GET", "/api/tv/visualizer/config", "library.read"),
    ("POST", "/api/tv/visualizer/stats", "play"),
    ("PUT", "/api/tv/visualizer/config", "library.manage"),
    ("GET", "/api/map/graph", "library.read"),
    ("POST", "/api/map/soundscape/recompute", "library.manage"),
    ("GET", "/api/discovery/lastfm/auth-url", "settings.manage"),
    ("GET", "/api/live/now-playing", "library.read"),
])
def test_policy_spot_checks(method, path, perm):
    assert perm_for(method, path) == perm


# --- setup / login / logout / me ------------------------------------------------------

async def test_setup_only_when_empty(env):
    async with client() as c:
        r = await c.get("/api/auth/status")
        assert r.status_code == 200 and r.json()["needs_setup"] is True and r.json()["enforce"] is False
        r = await c.post("/api/auth/setup", json={"username": "owner", "password": "short"})
        assert r.status_code == 400
        r = await c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD, "display_name": "Spider"})
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["role"] == "admin" and me["is_admin"] and me["display_name"] == "Spider"
        assert me["auth_method"] == "session" and "users.manage" in me["permissions"]
        assert c.cookies.get("zonik_session")
        assert (await c.get("/api/auth/me")).json()["username"] == "owner"
        r = await c.post("/api/auth/setup", json={"username": "other", "password": PASSWORD})
        assert r.status_code == 409
        assert (await c.get("/api/auth/status")).json()["needs_setup"] is False
    async with async_session() as db:
        owner = (await db.execute(select(User).where(User.username == "owner"))).scalar_one()
        assert owner.is_admin and owner.subsonic_api_key


async def test_login_me_logout(env):
    await add_user()
    async with client() as c:
        assert (await c.get("/api/auth/me")).status_code == 401  # grace-anonymous isn't logged in
        r = await login(c, password="wrong")
        assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"
        r = await login(c)
        assert r.status_code == 200
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "secure" not in cookie
        me = (await c.get("/api/auth/me")).json()
        assert me["username"] == "admin" and me["auth_method"] == "session"
        assert me["must_change_password"] is False
        r = await c.put("/api/auth/me", json={"display_name": "Spider"})
        assert r.json()["display_name"] == "Spider"
        assert (await c.post("/api/auth/logout")).status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 401
    async with async_session() as db:
        assert (await db.execute(select(AuthSession))).scalars().all() == []
        user = (await db.execute(select(User))).scalar_one()
        assert user.last_login_at is not None


async def test_must_change_password_for_default_admin(env):
    await add_user(password="admin")
    async with client() as c:
        assert (await login(c, password="admin")).json()["must_change_password"] is True
        r = await c.post("/api/auth/password", json={"current_password": "admin", "new_password": "admin"})
        assert r.status_code == 400
        r = await c.post("/api/auth/password", json={"current_password": "admin", "new_password": PASSWORD})
        assert r.status_code == 200
        assert (await c.get("/api/auth/me")).json()["must_change_password"] is False


async def test_password_change_keeps_this_session_only(env):
    await add_user()
    async with client() as a, client() as b:
        await login(a)
        await login(b)
        tok_r = await b.post("/api/auth/device", json={"username": "admin", "password": PASSWORD, "platform": "tv"})
        token = tok_r.json()["token"]
        r = await a.post("/api/auth/password", json={"current_password": "nope", "new_password": "another pass"})
        assert r.status_code == 403
        r = await a.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "another pass"})
        assert r.status_code == 200
        assert (await a.get("/api/auth/me")).status_code == 200
        assert (await b.get("/api/auth/me")).status_code == 401
        # device tokens are untouched
        r = await b.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200


async def test_lockout(env):
    await add_user()
    async with client() as c:
        for _ in range(5):
            assert (await login(c, password="bad")).status_code == 401
        r = await login(c)  # right password, still locked
        assert r.status_code == 429 and r.json()["detail"].startswith("Too many attempts, try again in ")
        # the device endpoint shares the lockout
        r = await c.post("/api/auth/device", json={"username": "ADMIN", "password": PASSWORD})
        assert r.status_code == 429
    async with client("10.0.0.51") as other:  # another IP isn't locked
        assert (await login(other)).status_code == 200


async def test_disabled_user_rejected_everywhere(env, monkeypatch):
    await add_user()
    user = await add_user("guest", role="user", api_key="guestkey")
    async with client() as c:
        token = (await c.post("/api/auth/device", json={"username": "guest", "password": PASSWORD})).json()["token"]
        await login(c, "guest")
        async with async_session() as db:
            row = await db.get(User, user.id)
            row.disabled = True
            await db.commit()
        assert (await c.get("/api/auth/me")).status_code == 401  # session no longer resolves
        assert (await login(c, "guest")).status_code == 403
        assert (await login(c, "guest")).json()["detail"] == "Account disabled"
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401
        r = await c.get("/api/auth/me", params=subsonic_params("guest", "guestkey"))
        assert r.status_code == 401
        enforce(monkeypatch)
        r = await c.get("/rest/getGenres", params=subsonic_params("guest", "guestkey"))
        assert r.json()["subsonic-response"]["error"]["code"] == 40

    from fastapi import HTTPException
    from backend.subsonic.auth import authenticate_subsonic
    with pytest.raises(HTTPException):
        await authenticate_subsonic(_bare_request(subsonic_params("guest", "guestkey")))


def _bare_request(params: dict):
    from urllib.parse import urlencode
    from starlette.requests import Request
    return Request({"type": "http", "method": "GET", "path": "/rest/star", "headers": [],
                    "query_string": urlencode(params).encode(), "client": ("10.0.0.50", 1)})


# --- grace vs enforce -----------------------------------------------------------------

async def test_grace_mode_runs_anonymous_requests_as_owner(env, caplog):
    await add_user()
    async with client() as c:
        r = await c.get("/api/users")
        assert r.status_code == 200 and r.json()[0]["username"] == "admin"
        assert (await c.get("/api/users")).status_code == 200
    grace = [rec for rec in caplog.records if "auth grace: unauthenticated GET /api/users" in rec.getMessage()]
    assert len(grace) == 1  # once per path per 10 minutes


async def test_enforce_mode_api(env, monkeypatch):
    await add_user()
    enforce(monkeypatch)
    async with client() as c:
        r = await c.get("/api/users")
        assert r.status_code == 401 and r.json() == {"detail": "Not authenticated"}
        assert (await c.get("/api/auth/status")).json()["enforce"] is True
        assert (await c.post("/api/pair")).status_code == 200  # public
        r = await c.post("/api/logs", json={"device": "d", "app_version": "1", "timestamp": "t", "logs": "x"})
        assert r.status_code == 200
        # bad credentials are no credentials
        assert (await c.get("/api/users", params=subsonic_params(key="wrong"))).status_code == 401
        # the phone's Subsonic params still work on /api
        assert (await c.get("/api/users", params=subsonic_params())).status_code == 200
        assert (await c.get("/api/users", params={"apiKey": API_KEY})).status_code == 200
        await login(c)
        assert (await c.get("/api/users")).status_code == 200


async def test_subsonic_params_resolve_on_api(env):
    await add_user()
    async with client() as c:
        me = (await c.get("/api/auth/me", params=subsonic_params())).json()
        assert me["auth_method"] == "subsonic" and me["username"] == "admin"
        r = await c.get("/api/auth/me", params={"u": "admin", "p": "enc:" + PASSWORD.encode().hex()})
        assert r.json()["auth_method"] == "subsonic"


async def test_grace_survives_missing_auth_columns(env):
    """Between upgrade.sh restarting on the new code and `alembic upgrade head`, users has no
    role column. Grace mode must keep /api routes that don't read users working."""
    from sqlalchemy import text
    from backend.database import engine
    await add_user()
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP INDEX IF EXISTS ix_users_subsonic_api_key")
        await conn.execute(text("ALTER TABLE users DROP COLUMN role"))
    async with client() as c:
        assert (await c.get("/api/config/version")).status_code == 200
        assert (await c.get("/api/config/version", params=subsonic_params())).status_code == 200
        r = await c.get("/rest/getGenres", params=subsonic_params())
        assert r.json()["subsonic-response"]["status"] == "ok"


async def test_enforce_internal_loopback_paths(env, monkeypatch):
    await add_user()
    enforce(monkeypatch)
    async with client("127.0.0.1") as c:
        assert (await c.get("/api/download/status")).status_code == 200
        assert (await c.get("/api/users")).status_code == 401
        r = await c.get("/api/download/status", headers={"X-Forwarded-For": "1.2.3.4"})
        assert r.status_code == 401


async def test_rest_grace_and_enforce(env, monkeypatch):
    await add_user()
    async with client() as c:
        r = await c.get("/rest/getGenres", params={"f": "json"})
        assert r.json()["subsonic-response"]["status"] == "ok"  # grace: as before
        enforce(monkeypatch)
        r = await c.get("/rest/getGenres", params={"f": "json"})
        body = r.json()["subsonic-response"]
        assert body["status"] == "failed" and body["error"]["code"] == 40
        r = await c.get("/rest/getGenres.view", params={"f": "xml"})
        assert r.headers["content-type"].startswith("application/xml") and 'code="40"' in r.text
        for open_ep in ("ping.view", "getLicense", "getOpenSubsonicExtensions.view"):
            r = await c.get(f"/rest/{open_ep}", params={"f": "json"})
            assert r.json()["subsonic-response"]["status"] == "ok", open_ep
        r = await c.get("/rest/getGenres", params=subsonic_params())
        assert r.json()["subsonic-response"]["status"] == "ok"
        await login(c)  # the web player's cookie counts too
        assert (await c.get("/rest/getGenres")).json()["subsonic-response"]["status"] == "ok"


# --- roles ------------------------------------------------------------------------------

@pytest.mark.parametrize("enforced", [False, True])
async def test_user_role_gets_403_on_admin_routes(env, monkeypatch, enforced):
    await add_user()
    await add_user("guest", role="user", api_key="guestkey")
    enforce(monkeypatch, enforced)
    async with client() as c:
        await login(c, "guest")
        me = (await c.get("/api/auth/me")).json()
        assert me["role"] == "user" and not me["is_admin"]
        assert sorted(me["permissions"]) == ["downloads.use", "library.read", "own.write", "play"]
        r = await c.get("/api/users")
        assert r.status_code == 403 and r.json() == {"detail": "Admins only"}
        assert (await c.get("/api/config/services")).status_code == 403
        assert (await c.get("/api/logs/app")).status_code == 403
        assert (await c.get("/api/config/version")).status_code == 200
        assert (await c.get("/api/config/shuffle")).status_code == 200
        # Subsonic params as a user: same rules
    async with client() as c:
        r = await c.get("/api/users", params=subsonic_params("guest", "guestkey"))
        assert r.status_code == 403


# --- device tokens ----------------------------------------------------------------------

async def test_device_token_bearer_and_apikey(env, monkeypatch):
    await add_user()
    async with client() as c:
        r = await c.post("/api/auth/device", json={"username": "admin", "password": PASSWORD,
                                                    "label": "Living room TV", "platform": "tv"})
        assert r.status_code == 200
        token = r.json()["token"]
        assert token.startswith("zk_") and r.json()["user"]["auth_method"] == "device"
        assert (await c.post("/api/auth/device", json={"username": "admin", "password": "x"})).status_code == 401
    enforce(monkeypatch)
    async with client() as c:
        me = (await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).json()
        assert me["auth_method"] == "device"
        me = (await c.get("/api/auth/me", params={"apiKey": token})).json()
        assert me["auth_method"] == "device"
        r = await c.get("/rest/getGenres", params={"apiKey": token, "f": "json"})
        assert r.json()["subsonic-response"]["status"] == "ok"
        devices = (await c.get("/api/auth/devices", headers={"Authorization": f"Bearer {token}"})).json()
        assert [d for d in devices if d["kind"] == "device" and d["current"] and d["platform"] == "tv"]

    from backend.subsonic.auth import authenticate_subsonic
    user = await authenticate_subsonic(_bare_request({"apiKey": token}))
    assert user.username == "admin"
    user = await authenticate_subsonic(_bare_request({"apiKey": API_KEY}))  # legacy key still works
    assert user.username == "admin"
    async with async_session() as db:
        row = (await db.execute(select(DeviceToken))).scalar_one()
        assert row.token_hash != token and row.last_seen_at is not None


async def test_devices_list_and_revoke(env):
    await add_user()
    async with client() as a, client() as b:
        await login(a)
        await login(b)
        token = (await a.post("/api/auth/device", json={"username": "admin", "password": PASSWORD})).json()["token"]
        items = (await a.get("/api/auth/devices")).json()
        assert sorted(i["kind"] for i in items) == ["device", "session", "session"]
        assert sum(1 for i in items if i["current"]) == 1
        device_id = next(i["id"] for i in items if i["kind"] == "device")
        other_session = next(i["id"] for i in items if i["kind"] == "session" and not i["current"])
        assert (await a.delete(f"/api/auth/devices/{device_id}")).status_code == 200
        async with client() as fresh:  # no cookie, so only the Bearer token counts
            assert (await fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
        assert (await a.delete(f"/api/auth/devices/{other_session}")).status_code == 200
        assert (await b.get("/api/auth/me")).status_code == 401
        assert (await a.delete("/api/auth/devices/nope")).status_code == 404
        current = next(i["id"] for i in (await a.get("/api/auth/devices")).json() if i["current"])
        r = await a.delete(f"/api/auth/devices/{current}")
        assert r.status_code == 200 and "zonik_session" in r.headers.get("set-cookie", "")


# --- /api/users -------------------------------------------------------------------------

async def test_users_crud_and_guards(env):
    admin = await add_user()
    async with client() as c:
        await login(c)
        r = await c.post("/api/users", json={"username": "kid", "password": PASSWORD, "display_name": "Kid"})
        kid_id = r.json()["id"]
        r = await c.post("/api/users", json={"username": "ops", "password": PASSWORD, "is_admin": True})
        ops_id = r.json()["id"]
        rows = {u["username"]: u for u in (await c.get("/api/users")).json()}
        assert rows["kid"]["role"] == "user" and rows["kid"]["display_name"] == "Kid"
        assert rows["ops"]["role"] == "admin" and rows["ops"]["is_admin"] is True
        assert set(rows["admin"]) >= {"display_name", "role", "disabled", "last_login_at", "subsonic_api_key"}

        # yourself: no demote, disable or delete
        for call in (c.put(f"/api/users/{admin.id}", json={"role": "user"}),
                     c.put(f"/api/users/{admin.id}", json={"disabled": True}),
                     c.delete(f"/api/users/{admin.id}")):
            r = await call
            assert r.status_code == 400 and "your own account" in r.json()["detail"]

        r = await c.put(f"/api/users/{ops_id}", json={"role": "user", "display_name": "Ops"})
        assert r.status_code == 200 and r.json()["role"] == "user" and r.json()["is_admin"] is False
        async with async_session() as db:
            assert (await db.get(User, ops_id)).is_admin is False

        assert (await c.post(f"/api/users/{kid_id}/reset-password", json={"new_password": "x"})).status_code == 400
        assert (await c.post(f"/api/users/{kid_id}/reset-password", json={"new_password": "new password"})).status_code == 200
        assert (await c.delete(f"/api/users/{kid_id}")).status_code == 200


async def test_last_enabled_admin_guard(env):
    import backend.api.users as users_api
    from fastapi import HTTPException
    admin = await add_user()
    request = SimpleNamespace(state=SimpleNamespace(user=None))  # no caller: only the last-admin rule applies
    async with async_session() as db:
        with pytest.raises(HTTPException) as e:
            await users_api.update_user(admin.id, users_api.UserUpdate(disabled=True), request, db)
        assert e.value.status_code == 400 and "last enabled admin" in e.value.detail
        with pytest.raises(HTTPException):
            await users_api.delete_user(admin.id, request, db)


async def test_disabling_ends_sessions_and_devices(env):
    await add_user()
    guest = await add_user("guest", role="user", api_key=None)
    async with client() as admin_c, client() as guest_c:
        await login(admin_c)
        await login(guest_c, "guest")
        token = (await guest_c.post("/api/auth/device", json={"username": "guest", "password": PASSWORD})).json()["token"]
        assert (await admin_c.put(f"/api/users/{guest.id}", json={"disabled": True})).json()["disabled"] is True
        assert (await guest_c.get("/api/auth/me")).status_code == 401
    async with async_session() as db:
        assert (await db.execute(select(AuthSession).where(AuthSession.user_id == guest.id))).scalars().all() == []
        row = (await db.execute(select(DeviceToken).where(DeviceToken.user_id == guest.id))).scalar_one()
        assert row.revoked_at is not None
    assert token


# --- CSRF -------------------------------------------------------------------------------

async def test_csrf_origin_check(env):
    await add_user()
    async with client() as c:
        await login(c)
        r = await c.put("/api/auth/me", json={"display_name": "x"}, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
        r = await c.put("/api/auth/me", json={"display_name": "x"}, headers={"Origin": "http://testserver"})
        assert r.status_code == 200
        assert (await c.put("/api/auth/me", json={"display_name": "y"})).status_code == 200
        # GETs and non-cookie callers aren't checked
        assert (await c.get("/api/auth/me", headers={"Origin": "http://evil.example"})).status_code == 200
        token = (await c.post("/api/auth/device", json={"username": "admin", "password": PASSWORD})).json()["token"]
    async with client() as d:
        r = await d.put("/api/auth/me", json={"display_name": "z"},
                        headers={"Origin": "http://evil.example", "Authorization": f"Bearer {token}"})
        assert r.status_code == 200


# --- websocket --------------------------------------------------------------------------

async def test_websocket_auth(env, monkeypatch):
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from urllib.parse import urlencode
    await add_user()
    tc = TestClient(app)
    with tc.websocket_connect("/api/ws"):  # grace: anonymous allowed
        pass
    enforce(monkeypatch)
    with pytest.raises(WebSocketDisconnect):
        with tc.websocket_connect("/api/ws"):
            pass
    with tc.websocket_connect("/api/ws?" + urlencode(subsonic_params())):
        pass


# Mark the async tests only (a module-wide pytestmark warns on the sync policy tests).
for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and inspect.iscoroutinefunction(_fn):
        globals()[_name] = pytest.mark.asyncio(_fn)
