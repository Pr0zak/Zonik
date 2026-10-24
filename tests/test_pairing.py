"""P4 pairing v2 + LAN discovery: the legacy TV flow (create/poll/submit) unchanged, the new
info/approve/qr endpoints (approve needs real credentials, 401 in grace mode too), the TV's
ready poll carrying a working device token, 409 double approve, expiry, the /info lockout,
/api/auth/status server_name/url, the UDP probe responder and the zeroconf registration with
AsyncZeroconf mocked (nothing here ever multicasts).

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_pairing.py
"""
import asyncio
import hashlib
import inspect
import json
import socket
import uuid
from unittest import mock

import httpx
import pytest
import pytest_asyncio

from backend.api import pair as pair_api
from backend.auth import lockout
from backend.auth.passwords import hash_password
from backend.auth.policy import PUBLIC, perm_for
from backend.auth.resolve import reset_grace_log
from backend.config import get_settings
from backend.database import async_session
from backend.main import app
from backend.middleware.rate_limit import RateLimiter
from backend.models.user import User
from backend.services import discovery

PASSWORD = "correct horse"
ADVERTISE = "http://zonik.test:3000"

app.user_middleware = [m for m in app.user_middleware if m.cls is not RateLimiter]
app.middleware_stack = None


@pytest_asyncio.fixture
async def env(db_ready, monkeypatch):
    lockout.reset_all()
    reset_grace_log()
    pair_api._pairs.clear()
    monkeypatch.setattr(get_settings().auth, "enforce", False)
    monkeypatch.setattr(get_settings().discovery, "advertise_url", ADVERTISE)
    yield
    lockout.reset_all()
    pair_api._pairs.clear()


def client(addr: str = "10.0.0.70") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(addr, 5555)),
                             base_url="http://testserver")


async def add_user(username="admin", role="admin", api_key: str | None = "k" * 32,
                   display_name: str | None = None) -> User:
    async with async_session() as db:
        user = User(id=str(uuid.uuid4()), username=username, password_hash=hash_password(PASSWORD),
                    subsonic_api_key=api_key, role=role, display_name=display_name)
        db.add(user)
        await db.commit()
        return user


async def login(c: httpx.AsyncClient, username="admin") -> None:
    r = await c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text


async def new_code(c: httpx.AsyncClient, **body) -> str:
    r = await (c.post("/api/pair", json=body) if body else c.post("/api/pair"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) == {"code", "expires"}
    assert len(data["code"]) == 6 and data["code"].isdigit()
    return data["code"]


# --- policy ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path,perm", [
    ("POST", "/api/pair", PUBLIC),
    ("GET", "/api/pair/123456", PUBLIC),
    ("POST", "/api/pair/123456/submit", PUBLIC),
    ("GET", "/api/pair/123456/info", PUBLIC),
    ("GET", "/api/pair/123456/qr.svg", PUBLIC),
    ("POST", "/api/pair/123456/approve", "own.write"),
])
def test_policy(method, path, perm):
    assert perm_for(method, path) == perm


# --- legacy flow ----------------------------------------------------------------------

async def test_legacy_flow_unchanged(env):
    async with client() as tv:
        code = await new_code(tv)
        assert (await tv.get(f"/api/pair/{code}")).json() == {"status": "pending"}
        r = await tv.post(f"/api/pair/{code}/submit",
                          json={"url": "http://x:3000", "username": "admin", "api_key": "abc"})
        assert r.json() == {"status": "ok"}
        assert (await tv.get(f"/api/pair/{code}")).json() == {
            "status": "ready", "url": "http://x:3000", "username": "admin", "api_key": "abc"}
        assert (await tv.get(f"/api/pair/{code}")).json() == {"status": "expired"}  # consumed
        assert (await tv.get("/api/pair/000000")).json() == {"status": "expired"}
        r = await tv.post("/api/pair/000000/submit", json={"url": "u", "username": "u", "api_key": "k"})
        assert r.status_code == 404
        # Odd bodies on create are tolerated (the old TV app sends none).
        r = await tv.post("/api/pair", content=b"not json", headers={"content-type": "application/json"})
        assert r.status_code == 200 and set(r.json()) == {"code", "expires"}


async def test_create_records_label_platform(env):
    async with client() as tv:
        code = await new_code(tv, label="Living room TV", platform="tv")
        info = (await tv.get(f"/api/pair/{code}/info")).json()
    assert info["status"] == "pending" and info["label"] == "Living room TV" and info["platform"] == "tv"
    assert info["created_at"].endswith("Z") and info["expires"].endswith("Z")
    stored = pair_api._pairs[code]
    assert stored["ip"] == "10.0.0.70"


# --- approve --------------------------------------------------------------------------

async def test_approve_requires_real_credentials(env, monkeypatch):
    await add_user()
    async with client() as tv:
        code = await new_code(tv)
        # Grace mode: the anonymous owner stand-in is not enough.
        assert (await tv.post(f"/api/pair/{code}/approve", json={})).status_code == 401
        monkeypatch.setattr(get_settings().auth, "enforce", True)
        assert (await tv.post(f"/api/pair/{code}/approve", json={})).status_code == 401
        assert (await tv.get(f"/api/pair/{code}")).json() == {"status": "pending"}


async def test_approve_flow_device_token_works(env, monkeypatch):
    user = await add_user("sam", role="user", display_name="Sam")
    async with client("10.0.0.71") as tv, client("10.0.0.72") as web:
        code = await new_code(tv, label="Living room TV", platform="tv")
        await login(web, "sam")
        r = await web.post(f"/api/pair/{code}/approve")  # no body
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["device"]["label"] == "Living room TV" and body["device"]["platform"] == "tv"

        # Second approve, before or after the TV picks it up -> 409.
        assert (await web.post(f"/api/pair/{code}/approve", json={})).status_code == 409
        assert (await web.get(f"/api/pair/{code}/info")).json() == {"status": "expired"}

        ready = (await tv.get(f"/api/pair/{code}")).json()
        assert ready["status"] == "ready"
        assert ready["url"] == ADVERTISE and ready["username"] == "sam"
        assert ready["api_key"] == user.subsonic_api_key and ready["display_name"] == "Sam"
        token = ready["device_token"]
        assert token.startswith("zk_")
        assert (await tv.get(f"/api/pair/{code}")).json() == {"status": "expired"}
        assert (await web.post(f"/api/pair/{code}/approve", json={})).status_code == 404

    monkeypatch.setattr(get_settings().auth, "enforce", True)
    async with client() as tv:
        me = (await tv.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).json()
        assert me["username"] == "sam" and me["auth_method"] == "device"
        r = await tv.get("/rest/getGenres", params={"apiKey": token, "f": "json"})
        assert r.json()["subsonic-response"]["status"] == "ok"
        # The legacy api_key still works as md5(key+salt) for the old TV app.
        salt = "s4lt"
        t = hashlib.md5((ready["api_key"] + salt).encode()).hexdigest()
        r = await tv.get("/rest/ping", params={"u": "sam", "t": t, "s": salt, "c": "t", "v": "1.16.1", "f": "json"})
        assert r.json()["subsonic-response"]["status"] == "ok"
        devices = (await tv.get("/api/auth/devices", headers={"Authorization": f"Bearer {token}"})).json()
        assert [d for d in devices if d["kind"] == "device" and d["current"] and d["platform"] == "tv"]


async def test_approve_defaults_and_generates_api_key(env, monkeypatch):
    await add_user("nokey", role="user", api_key=None)
    monkeypatch.setattr(get_settings().discovery, "advertise_url", "")
    monkeypatch.setattr(discovery, "primary_ipv4", lambda: None)  # no LAN IP -> request base url
    async with client() as tv, client() as web:
        code = await new_code(tv)
        await login(web, "nokey")
        r = await web.post(f"/api/pair/{code}/approve", json={"label": "  Den  "})
        assert r.status_code == 200
        assert r.json()["device"]["label"] == "Den" and r.json()["device"]["platform"] == "tv"
        ready = (await tv.get(f"/api/pair/{code}")).json()
    assert ready["url"] == "http://testserver" and ready["display_name"] == "nokey"
    assert ready["api_key"] and len(ready["api_key"]) == 32
    async with async_session() as db:
        from sqlalchemy import select
        stored = (await db.execute(select(User).where(User.username == "nokey"))).scalar_one()
        assert stored.subsonic_api_key == ready["api_key"]

    async with client() as tv, client() as web:
        code = await new_code(tv)
        await login(web, "nokey")
        assert (await web.post(f"/api/pair/{code}/approve")).json()["device"]["label"] == "TV"


async def test_approve_unknown_code(env):
    await add_user()
    async with client() as web:
        await login(web)
        r = await web.post("/api/pair/123456/approve", json={})
        assert r.status_code == 404 and r.json()["detail"] == "Code expired or invalid"


async def test_expiry(env, monkeypatch):
    await add_user()
    async with client() as tv, client() as web:
        code = await new_code(tv)
        pair_api._pairs[code]["expires_at"] -= pair_api.EXPIRY_SECONDS + 1
        assert (await tv.get(f"/api/pair/{code}")).json() == {"status": "expired"}
        code = await new_code(tv)
        pair_api._pairs[code]["expires_at"] -= pair_api.EXPIRY_SECONDS + 1
        assert (await tv.get(f"/api/pair/{code}/info")).json() == {"status": "expired"}
        assert (await tv.get(f"/api/pair/{code}/qr.svg")).status_code == 404
        await login(web)
        assert (await web.post(f"/api/pair/{code}/approve", json={})).status_code == 404


async def test_info_lockout(env, monkeypatch):
    monkeypatch.setattr(get_settings().auth, "login_max_failures", 3)
    async with client("10.0.0.90") as bad, client("10.0.0.91") as good:
        code = await new_code(good)
        for _ in range(3):
            assert (await bad.get("/api/pair/999999/info")).json() == {"status": "expired"}
        assert (await bad.get(f"/api/pair/{code}/info")).status_code == 429
        assert (await good.get(f"/api/pair/{code}/info")).json()["status"] == "pending"


async def test_qr(env):
    async with client() as tv:
        code = await new_code(tv)
        r = await tv.get(f"/api/pair/{code}/qr.svg")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in r.text
        assert (await tv.get("/api/pair/000000/qr.svg")).status_code == 404


async def test_qr_encodes_pair_url(env, monkeypatch):
    seen = []
    import segno
    real = segno.make

    def spy(content, **kw):
        seen.append(content)
        return real(content, **kw)
    monkeypatch.setattr(segno, "make", spy)
    async with client() as tv:
        code = await new_code(tv)
        assert (await tv.get(f"/api/pair/{code}/qr.svg")).status_code == 200
    assert seen == [f"{ADVERTISE}/pair?code={code}"]


async def test_auth_status_has_server_name_and_url(env, monkeypatch):
    async with client() as c:
        s = (await c.get("/api/auth/status")).json()
        assert s["server_name"] == "Zonik" and s["url"] == ADVERTISE
        assert {"needs_setup", "enforce", "version"} <= set(s)
        monkeypatch.setattr(get_settings().discovery, "name", "Den Zonik")
        assert (await c.get("/api/auth/status")).json()["server_name"] == "Den Zonik"


# --- discovery ------------------------------------------------------------------------

def test_advertise_url(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s.discovery, "advertise_url", "http://music.lan:3000/")
    assert discovery.advertise_url() == "http://music.lan:3000"
    monkeypatch.setattr(s.discovery, "advertise_url", "")
    monkeypatch.setattr(discovery, "primary_ipv4", lambda: "192.168.1.5")
    assert discovery.advertise_url() == f"http://192.168.1.5:{s.server.port}"


async def test_udp_probe_responder(monkeypatch):
    monkeypatch.setattr(get_settings().discovery, "advertise_url", ADVERTISE)
    d = discovery.Discovery()
    await d.start_udp("127.0.0.1", 0)
    assert d.udp_transport is not None
    port = d.udp_transport.get_extra_info("sockname")[1]
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        sock.bind(("127.0.0.1", 0))
        sock.sendto(b"hello", ("127.0.0.1", port))  # ignored
        sock.sendto(b"ZONIK? v1", ("127.0.0.1", port))
        data = await asyncio.wait_for(loop.sock_recv(sock, 2048), 2)
        reply = json.loads(data)
        assert reply["zonik"] == 1 and reply["name"] == "Zonik" and reply["url"] == ADVERTISE
        assert reply["version"]
        # Rate cap: a burst gets at most RATE_PER_SEC replies.
        for _ in range(20):
            sock.sendto(b"ZONIK?", ("127.0.0.1", port))
        got = 0
        try:
            while True:
                await asyncio.wait_for(loop.sock_recv(sock, 2048), 0.3)
                got += 1
        except asyncio.TimeoutError:
            pass
        assert 1 <= got <= discovery.RATE_PER_SEC
    finally:
        sock.close()
        await d.stop()
    assert d.udp_transport is None


async def test_udp_bind_failure_only_warns(caplog):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    try:
        d = discovery.Discovery()
        await d.start_udp("127.0.0.1", blocker.getsockname()[1])
        assert d.udp_transport is None
        assert "UDP probe responder not started" in caplog.text
        await d.stop()
    finally:
        blocker.close()


class FakeAsyncZeroconf:
    instances: list = []

    def __init__(self, *a, **kw):
        self.kwargs = kw
        self.registered = []
        self.unregistered = []
        self.closed = False
        FakeAsyncZeroconf.instances.append(self)

    async def async_register_service(self, info, **kw):
        self.registered.append((info, kw))

        async def done():
            return None
        return asyncio.ensure_future(done())

    async def async_unregister_service(self, info):
        self.unregistered.append(info)

        async def done():
            return None
        return asyncio.ensure_future(done())

    async def async_close(self):
        self.closed = True


async def test_discovery_start_stop_with_zeroconf_mocked(monkeypatch):
    import zeroconf.asyncio as zc_asyncio
    FakeAsyncZeroconf.instances.clear()
    monkeypatch.setattr(zc_asyncio, "AsyncZeroconf", FakeAsyncZeroconf)
    s = get_settings()
    monkeypatch.setattr(s.discovery, "enabled", True)
    monkeypatch.setattr(s.discovery, "udp_port", 0)
    monkeypatch.setattr(s.discovery, "advertise_url", ADVERTISE)
    monkeypatch.setattr(discovery, "host_ipv4s", lambda: ["192.168.1.5"])
    monkeypatch.setattr(discovery, "primary_ipv4", lambda: "192.168.1.5")
    with mock.patch.object(discovery.Discovery, "start_udp") as start_udp:  # no real socket here
        d = await discovery.start_discovery()
        start_udp.assert_called_once_with("0.0.0.0", 0)
    await asyncio.wait_for(d._task, 2)
    assert d.registered
    (azc,) = FakeAsyncZeroconf.instances
    info, kw = azc.registered[0]
    assert kw == {"allow_name_change": True}
    assert info.type == "_zonik._tcp.local." and info.name == "Zonik._zonik._tcp.local."
    assert info.port == s.server.port
    assert info.parsed_addresses() == ["192.168.1.5"]
    props = {k.decode(): v.decode() for k, v in info.properties.items()}
    assert props["url"] == ADVERTISE and props["name"] == "Zonik" and props["api"] == "1"
    assert props["path"] == "/" and props["scheme"] == "http" and props["version"]
    await discovery.stop_discovery(d)
    assert azc.unregistered == [info] and azc.closed and d.azc is None


async def test_discovery_disabled_and_failures(monkeypatch, caplog):
    s = get_settings()
    assert s.discovery.enabled is False  # the suite never starts discovery unless a test opts in
    assert await discovery.start_discovery() is None

    import zeroconf.asyncio as zc_asyncio

    class Broken(FakeAsyncZeroconf):
        async def async_register_service(self, info, **kw):
            raise OSError("no multicast route")
    monkeypatch.setattr(zc_asyncio, "AsyncZeroconf", Broken)
    monkeypatch.setattr(s.discovery, "enabled", True)
    monkeypatch.setattr(discovery, "host_ipv4s", lambda: ["192.168.1.5"])
    monkeypatch.setattr(discovery, "primary_ipv4", lambda: "192.168.1.5")
    with mock.patch.object(discovery.Discovery, "start_udp"):
        d = await discovery.start_discovery()
    await asyncio.wait_for(d._task, 2)
    assert not d.registered and "mDNS registration failed" in caplog.text
    await discovery.stop_discovery(d)


for _name, _fn in list(globals().items()):
    if _name.startswith("test_") and inspect.iscoroutinefunction(_fn):
        globals()[_name] = pytest.mark.asyncio(_fn)
