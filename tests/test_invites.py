"""P3 invites + admin device management: create/list/revoke/QR (admin only), the public
invite lookup and /api/auth/join (happy path, reuse, expired, revoked, duplicate username,
weak password, a concurrent double-use), the code-guess lockout and /api/users/{id}/devices.

Run: uv run --with pytest --with pytest-asyncio --with segno pytest tests/test_invites.py
"""
import asyncio
import inspect
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.auth import lockout
from backend.auth.passwords import hash_password
from backend.auth.policy import PUBLIC, perm_for
from backend.auth.resolve import reset_grace_log
from backend.config import get_settings
from backend.database import async_session
from backend.main import app
from backend.middleware.rate_limit import RateLimiter
from backend.models.auth import AuthSession, DeviceToken
from backend.models.invite import Invite
from backend.models.user import User

PASSWORD = "correct horse"
INVALID = "This invite link is invalid or has expired"

app.user_middleware = [m for m in app.user_middleware if m.cls is not RateLimiter]
app.middleware_stack = None


@pytest_asyncio.fixture
async def env(db_ready, monkeypatch):
    lockout.reset_all()
    reset_grace_log()
    monkeypatch.setattr(get_settings().auth, "enforce", True)
    yield
    lockout.reset_all()


def client(addr: str = "10.0.0.60") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(addr, 5555)),
                             base_url="http://testserver")


async def add_user(username="admin", role="admin") -> User:
    async with async_session() as db:
        user = User(id=str(uuid.uuid4()), username=username, password_hash=hash_password(PASSWORD),
                    subsonic_api_key=uuid.uuid4().hex, role=role, display_name=username.title())
        db.add(user)
        await db.commit()
        return user


async def login(c: httpx.AsyncClient, username="admin") -> None:
    r = await c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text


@asynccontextmanager
async def admin_client():
    async with client("10.0.0.10") as c:
        await login(c)
        yield c


async def make_invite(c: httpx.AsyncClient, **body) -> dict:
    r = await c.post("/api/users/invites", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def join_body(code: str, username="newbie", password=PASSWORD, **extra) -> dict:
    return {"code": code, "username": username, "password": password, **extra}


# --- policy ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,perm", [
    ("GET", "/api/auth/invite/abc", PUBLIC),
    ("POST", "/api/auth/join", PUBLIC),
    ("GET", "/api/auth/devices", "own.write"),
    ("POST", "/api/users/invites", "users.manage"),
    ("GET", "/api/users/invites", "users.manage"),
    ("DELETE", "/api/users/invites/abc", "users.manage"),
    ("GET", "/api/users/invites/abc/qr.svg", "users.manage"),
    ("GET", "/api/users/abc/devices", "users.manage"),
    ("DELETE", "/api/users/abc/devices/def", "users.manage"),
])
def test_policy(method, path, perm):
    assert perm_for(method, path) == perm


# --- admin endpoints ------------------------------------------------------------------

async def test_create_list_revoke_qr(env):
    admin = await add_user()
    await add_user("guest", role="user")
    async with admin_client() as c:
        inv = await make_invite(c, note="  for Sam  ", expires_days=14)
        assert inv["role"] == "user" and inv["note"] == "for Sam" and inv["status"] == "active"
        assert inv["url"] == f"http://testserver/join/{inv['code']}"
        assert inv["created_by"] == {"id": admin.id, "username": "admin"} and inv["used_by"] is None
        assert inv["used_at"] is None
        exp = datetime.fromisoformat(inv["expires_at"]) - datetime.fromisoformat(inv["created_at"])
        assert exp == timedelta(days=14)
        adm = await make_invite(c, role="admin")
        assert adm["role"] == "admin"

        assert (await c.post("/api/users/invites", json={"role": "owner"})).status_code == 400
        for days in (0, 31):
            assert (await c.post("/api/users/invites", json={"expires_days": days})).status_code == 400

        listed = (await c.get("/api/users/invites")).json()
        assert [i["id"] for i in listed] == [adm["id"], inv["id"]]  # newest first
        r = await c.get("/api/users/invites", headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "zonik.example"})
        assert r.json()[0]["url"] == f"https://zonik.example/join/{adm['code']}"

        r = await c.get(f"/api/users/invites/{inv['id']}/qr.svg")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in r.text
        assert (await c.get("/api/users/invites/nope/qr.svg")).status_code == 404

        assert (await c.delete(f"/api/users/invites/{adm['id']}")).status_code == 200
        assert (await c.delete("/api/users/invites/nope")).status_code == 404
        assert [i["id"] for i in (await c.get("/api/users/invites")).json()] == [inv["id"]]
        every = (await c.get("/api/users/invites", params={"include_used": "true"})).json()
        assert {i["id"]: i["status"] for i in every} == {adm["id"]: "revoked", inv["id"]: "active"}

    async with client() as g:
        await login(g, "guest")
        assert (await g.post("/api/users/invites", json={})).status_code == 403
        assert (await g.get("/api/users/invites")).status_code == 403
        assert (await g.delete(f"/api/users/invites/{inv['id']}")).status_code == 403
        assert (await g.get(f"/api/users/invites/{inv['id']}/qr.svg")).status_code == 403
    async with client() as anon:  # enforce mode: no credentials
        assert (await anon.get("/api/users/invites")).status_code == 401


# --- public lookup + join ---------------------------------------------------------------

async def test_join_happy_path_logs_in_with_role(env):
    await add_user()
    async with admin_client() as c:
        inv = await make_invite(c, role="admin")
    async with client() as j:
        r = await j.get(f"/api/auth/invite/{inv['code']}")
        assert r.status_code == 200
        assert r.json() == {"valid": True, "role": "admin", "expires_at": inv["expires_at"], "invited_by": "Admin"}
        r = await j.post("/api/auth/join", json=join_body(inv["code"], "New.Admin", display_name=" Nat "))
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["username"] == "New.Admin" and me["role"] == "admin" and me["display_name"] == "Nat"
        assert me["auth_method"] == "session" and "users.manage" in me["permissions"]
        cookie = r.headers["set-cookie"].lower()
        assert "zonik_session" in cookie and "httponly" in cookie
        assert (await j.get("/api/auth/me")).json()["username"] == "New.Admin"
        assert (await j.get("/api/users")).status_code == 200  # admin role really applies
        # reuse fails, with the same message as an unknown code
        r = await j.post("/api/auth/join", json=join_body(inv["code"], "second"))
        assert r.status_code == 404 and r.json() == {"detail": INVALID}
        r = await j.get(f"/api/auth/invite/{inv['code']}")
        assert r.status_code == 404 and r.json() == {"detail": INVALID}
    async with async_session() as db:
        user = (await db.execute(select(User).where(User.username == "New.Admin"))).scalar_one()
        assert user.subsonic_api_key and user.last_login_at is not None
        row = (await db.execute(select(Invite))).scalar_one()
        assert row.used_at is not None and row.used_by == user.id
    async with admin_client() as c:
        used = (await c.get("/api/users/invites", params={"include_used": True})).json()[0]
        assert used["status"] == "used" and used["used_by"] == {"id": user.id, "username": "New.Admin"}
        assert (await c.delete(f"/api/users/invites/{used['id']}")).status_code == 400


async def test_join_user_role(env):
    await add_user()
    async with admin_client() as c:
        inv = await make_invite(c)
    async with client() as j:
        me = (await j.post("/api/auth/join", json=join_body(inv["code"]))).json()
        assert me["role"] == "user" and not me["is_admin"]
        assert (await j.get("/api/users")).status_code == 403


async def test_expired_revoked_unknown_fail(env):
    await add_user()
    async with admin_client() as c:
        expired = await make_invite(c)
        revoked = await make_invite(c)
        await c.delete(f"/api/users/invites/{revoked['id']}")
    async with async_session() as db:
        row = await db.get(Invite, expired["id"])
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        await db.commit()
    for i, code in enumerate((expired["code"], revoked["code"], "no-such-code")):
        async with client(f"10.0.1.{i}") as j:
            r = await j.get(f"/api/auth/invite/{code}")
            assert r.status_code == 404 and r.json()["detail"] == INVALID
            r = await j.post("/api/auth/join", json=join_body(code))
            assert r.status_code == 404 and r.json()["detail"] == INVALID
    async with admin_client() as c:
        statuses = {i["id"]: i["status"] for i in (await c.get("/api/users/invites?include_used=true")).json()}
        assert statuses == {expired["id"]: "expired", revoked["id"]: "revoked"}
    async with async_session() as db:
        assert len((await db.execute(select(User))).scalars().all()) == 1


async def test_username_and_password_rules(env):
    await add_user()
    async with admin_client() as c:
        inv = await make_invite(c)
    async with client() as j:
        r = await j.post("/api/auth/join", json=join_body(inv["code"], "ADMIN"))
        assert r.status_code == 409 and r.json()["detail"] == "Username already taken"
        for bad in ("ab", "x" * 33, "has space", "emojié"):
            assert (await j.post("/api/auth/join", json=join_body(inv["code"], bad))).status_code == 400, bad
        for weak in ("short", "admin"):
            r = await j.post("/api/auth/join", json=join_body(inv["code"], password=weak))
            assert r.status_code == 400, weak
        # none of the refusals consumed the invite
        assert (await j.get(f"/api/auth/invite/{inv['code']}")).status_code == 200
        assert (await j.post("/api/auth/join", json=join_body(inv["code"], "ok_name-1.x"))).status_code == 200


async def test_concurrent_double_use_only_one_wins(env):
    await add_user()
    async with admin_client() as c:
        inv = await make_invite(c)
    async with client("10.0.2.1") as a, client("10.0.2.2") as b:
        ra, rb = await asyncio.gather(
            a.post("/api/auth/join", json=join_body(inv["code"], "alpha")),
            b.post("/api/auth/join", json=join_body(inv["code"], "bravo")),
        )
    assert sorted([ra.status_code, rb.status_code]) == [200, 404]
    async with async_session() as db:
        names = {u.username for u in (await db.execute(select(User))).scalars().all()}
        assert names == {"admin", "alpha"} or names == {"admin", "bravo"}


async def test_failed_code_lookups_lock_out_the_ip(env):
    await add_user()
    async with admin_client() as c:
        inv = await make_invite(c)
    async with client("10.0.3.1") as j:
        for n in range(get_settings().auth.login_max_failures):
            assert (await j.get(f"/api/auth/invite/guess{n}")).status_code == 404
        r = await j.get(f"/api/auth/invite/{inv['code']}")  # right code, still locked
        assert r.status_code == 429 and r.json()["detail"].startswith("Too many attempts")
        assert (await j.post("/api/auth/join", json=join_body(inv["code"]))).status_code == 429
    async with client("10.0.3.2") as other:
        assert (await other.get(f"/api/auth/invite/{inv['code']}")).status_code == 200


# --- admin device management ------------------------------------------------------------

async def test_admin_user_devices(env):
    await add_user()
    guest = await add_user("guest", role="user")
    async with client("10.0.4.1") as g:
        await login(g, "guest")
        token = (await g.post("/api/auth/device", json={"username": "guest", "password": PASSWORD,
                                                         "platform": "tv", "label": "Den TV"})).json()["token"]
        own = (await g.get("/api/auth/devices")).json()
        assert (await g.get(f"/api/users/{guest.id}/devices")).status_code == 403
        async with admin_client() as c:
            items = (await c.get(f"/api/users/{guest.id}/devices")).json()
            assert {i["id"] for i in items} == {i["id"] for i in own}
            assert set(items[0]) == set(own[0])
            assert all(i["current"] is False for i in items)
            assert (await c.get("/api/users/nope/devices")).status_code == 404
            device_id = next(i["id"] for i in items if i["kind"] == "device")
            session_id = next(i["id"] for i in items if i["kind"] == "session")
            assert (await c.delete(f"/api/users/{guest.id}/devices/nope")).status_code == 404
            # someone else's item id under this user is a 404, not a revoke
            admin_items = (await c.get("/api/auth/devices")).json()
            assert (await c.delete(f"/api/users/{guest.id}/devices/{admin_items[0]['id']}")).status_code == 404
            assert (await c.delete(f"/api/users/{guest.id}/devices/{device_id}")).status_code == 200
            assert (await c.delete(f"/api/users/{guest.id}/devices/{session_id}")).status_code == 200
            assert (await c.get(f"/api/users/{guest.id}/devices")).json() == []
            assert (await c.get("/api/auth/me")).status_code == 200  # the admin's own session is untouched
        assert (await g.get("/api/auth/me")).status_code == 401
    async with client() as fresh:
        assert (await fresh.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401
    async with async_session() as db:
        assert (await db.execute(select(AuthSession).where(AuthSession.user_id == guest.id))).scalars().all() == []
        assert (await db.execute(select(DeviceToken).where(DeviceToken.user_id == guest.id))).scalar_one().revoked_at


async def test_deleting_users_with_invites(env):
    await add_user()
    ops = await add_user("ops")
    async with client() as o:
        await login(o, "ops")
        made = await make_invite(o)
    async with admin_client() as c:
        inv = await make_invite(c)
        async with client("10.0.5.1") as j:
            joined = (await j.post("/api/auth/join", json=join_body(inv["code"]))).json()
        assert (await c.delete(f"/api/users/{joined['id']}")).status_code == 200
        assert (await c.delete(f"/api/users/{ops.id}")).status_code == 200
        rows = (await c.get("/api/users/invites", params={"include_used": True})).json()
        assert [(r["id"], r["status"], r["used_by"]) for r in rows] == [(inv["id"], "used", None)]
    assert made


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and inspect.iscoroutinefunction(_fn):
        globals()[_name] = pytest.mark.asyncio(_fn)
