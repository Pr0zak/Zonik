"""Upload serving (we are the uploader) and the shared file list, without sockets.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_upload.py
"""
import asyncio
import struct
import time
from pathlib import Path

import pytest

from backend.soulseek import shares
from backend.soulseek.protocol.peer_messages import (
    build_transfer_response, build_upload_denied, parse_peer_message,
)
from backend.soulseek.protocol.types import (
    FileAttribute, PeerMessageCode, TransferDirection, TransferState,
)
from backend.soulseek.upload import (
    DENY_NOT_SHARED, DENY_NOT_SHARING, RateLimiter, UploadManager,
)

pytestmark = pytest.mark.asyncio


# --- fakes --------------------------------------------------------------------

class FakeWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, b):
        self.data += b

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed


class FakePeer:
    """Records every message sent on the P connection, parsed."""

    def __init__(self, username):
        self.username = username
        self.sent: list[dict] = []
        self.new_message = asyncio.Event()

    async def send_raw(self, data):
        (length,) = struct.unpack("<I", data[:4])
        assert length == len(data) - 4
        self.sent.append(parse_peer_message(data[4:]))
        self.new_message.set()

    async def send_upload_denied(self, filename, reason):
        await self.send_raw(build_upload_denied(filename, reason))

    async def send_transfer_response(self, token, allowed, reason=""):
        await self.send_raw(build_transfer_response(token, allowed, reason))

    def kinds(self):
        return [m["kind"] for m in self.sent]

    async def wait_for(self, kind, timeout=2.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            for m in self.sent:
                if m["kind"] == kind:
                    return m
            remaining = end - loop.time()
            if remaining <= 0:
                raise AssertionError(f"no {kind}; sent {self.kinds()}")
            self.new_message.clear()
            try:
                await asyncio.wait_for(self.new_message.wait(), remaining)
            except asyncio.TimeoutError:
                pass


def reader_with(data: bytes, eof: bool = True) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(data)
    if eof:
        r.feed_eof()
    return r


async def wait_until(cond, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.01)


@pytest.fixture
def library(tmp_path):
    """A music dir with three shared files, installed as the share list."""
    music = tmp_path / "music"
    files = {
        "Artist/Album/01 - One.flac": b"1" * 1000,
        "Artist/Album/02 - Two.flac": b"2" * 300_000,
        "Other/03 - Three.mp3": b"3" * 50,
    }
    for rel, data in files.items():
        p = music / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    entries = [shares.ShareEntry(rel_path=rel, size=len(data)) for rel, data in files.items()]
    shares.install(shares.build_share_list(str(music), entries))
    yield music, files
    shares.install(shares._empty_list())


def make_manager(peers=None, conns=None, *, slots=2, kbps=0, enabled=True):
    peers = peers if peers is not None else {}
    conns = conns if conns is not None else {}

    async def get_peer(username):
        return peers.setdefault(username, FakePeer(username))

    async def open_conn(username):
        return conns[username]

    return UploadManager(
        get_peer=get_peer, open_file_connection=open_conn,
        enabled=lambda: enabled, slots=slots, speed_limit_kbps=kbps,
    ), peers


ONE = "Artist\\Album\\01 - One.flac"
TWO = "Artist\\Album\\02 - Two.flac"
THREE = "Other\\03 - Three.mp3"


# --- queueing -----------------------------------------------------------------

async def test_queued_upload_gets_place_in_queue(library):
    um, peers = make_manager(slots=1)
    um._kick = lambda: None  # nothing starts: everything stays queued
    assert um.queue("alice", ONE) is None
    assert um.queue("bob", TWO) is None
    assert um.queue("alice", ONE) is None  # repeat is not a second entry
    assert len(um.uploads) == 2
    assert um.place_in_queue("alice", ONE) == 1
    assert um.place_in_queue("bob", TWO) == 2
    assert um.place_in_queue("bob", "Artist/Album/02 - Two.flac") == 2  # either separator
    assert um.place_in_queue("bob", THREE) is None


async def test_file_outside_shares_is_refused(library, tmp_path):
    secret = tmp_path / "secret.flac"
    secret.write_bytes(b"x" * 10)
    um, _ = make_manager()
    assert um.queue("eve", "..\\secret.flac") == DENY_NOT_SHARED
    assert um.queue("eve", str(secret)) == DENY_NOT_SHARED
    assert um.queue("eve", "Artist\\Album\\nope.flac") == DENY_NOT_SHARED
    assert um.uploads == {}


async def test_sharing_off_denies_everything(library):
    um, _ = make_manager(enabled=False)
    assert um.queue("alice", ONE) == DENY_NOT_SHARING
    assert um.uploads == {}


async def test_slot_limited_queue_serves_in_order(library):
    um, peers = make_manager(slots=1)
    for user, f in (("a", ONE), ("b", TWO), ("c", THREE)):
        assert um.queue(user, f) is None
    order = []
    for user in ("a", "b", "c"):
        await wait_until(lambda: user in peers and peers[user].sent)
        # only one request out at a time
        assert sum(1 for p in peers.values() for m in p.sent if m["kind"] == "transfer_request") == len(order) + 1
        req = await peers[user].wait_for("transfer_request")
        order.append(user)
        assert req["direction"] == TransferDirection.UPLOAD
        assert um.handle_transfer_response(user, req["token"], False, "Cancelled")
    assert order == ["a", "b", "c"]
    await wait_until(lambda: um.running() == 0)
    assert all(u.state == TransferState.DENIED for u in um.uploads.values())


async def test_one_upload_per_peer(library):
    um, peers = make_manager(slots=2)
    um.queue("a", ONE)
    um.queue("a", TWO)
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    await asyncio.sleep(0.05)
    assert um.running() == 1
    assert um.place_in_queue("a", TWO) == 1
    um.destroy()


async def test_peer_says_queued_keeps_it_queued(library):
    um, peers = make_manager(slots=1)
    um.queue("a", ONE)
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    req = peers["a"].sent[0]
    um.handle_transfer_response("a", req["token"], False, "Queued")
    await wait_until(lambda: um.running() == 0)
    up = um.uploads[("a", ONE)]
    assert up.state == TransferState.QUEUED and up.retry_at > time.time()


# --- the data phase -------------------------------------------------------------

@pytest.mark.parametrize("offset", [0, 123_456])
async def test_allowed_response_streams_file_from_offset(library, offset):
    music, files = library
    w = FakeWriter()
    conns = {"a": (reader_with(struct.pack("<Q", offset)), w)}
    um, peers = make_manager(conns=conns)
    assert um.queue("a", TWO) is None
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    req = peers["a"].sent[0]
    assert req["kind"] == "transfer_request"
    assert req["filename"] == TWO and req["size"] == 300_000
    assert um.handle_transfer_response("a", req["token"], True)
    up = um.uploads[("a", TWO)]
    await wait_until(lambda: up.state in (TransferState.COMPLETED, TransferState.FAILED))
    assert up.state == TransferState.COMPLETED, up.error
    data = bytes(w.data)
    assert data[:4] == req["token"]  # FileTransferInit: the bare token
    assert data[4:] == files["Artist/Album/02 - Two.flac"][offset:]
    assert up.offset == offset and up.sent_bytes == 300_000 - offset
    assert w.closed
    d = up.to_dict()
    assert d["direction"] == "upload" and d["progress"] == 100.0


async def test_offset_past_end_fails_and_tells_peer(library):
    w = FakeWriter()
    um, peers = make_manager(conns={"a": (reader_with(struct.pack("<Q", 10**9)), w)})
    um.queue("a", ONE)
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    um.handle_transfer_response("a", peers["a"].sent[0]["token"], True)
    up = um.uploads[("a", ONE)]
    await wait_until(lambda: up.state == TransferState.FAILED)
    await peers["a"].wait_for("upload_failed")
    assert bytes(w.data) == peers["a"].sent[0]["token"] and w.closed


async def test_no_transfer_response_fails(library, monkeypatch):
    import backend.soulseek.upload as upload_mod
    monkeypatch.setattr(upload_mod, "RESPONSE_TIMEOUT", 0.05)
    um, peers = make_manager()
    um.queue("a", ONE)
    up = um.uploads[("a", ONE)]
    await wait_until(lambda: up.state == TransferState.FAILED)
    assert up.error == "No response from peer"


async def test_destroy_cancels_running_uploads(library):
    r = asyncio.StreamReader()  # peer never sends its offset
    w = FakeWriter()
    um, peers = make_manager(conns={"a": (r, w)})
    um.start()
    um.queue("a", ONE)
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    um.handle_transfer_response("a", peers["a"].sent[0]["token"], True)
    up = um.uploads[("a", ONE)]
    await wait_until(lambda: bytes(w.data))  # FileTransferInit sent, now waiting for the offset
    task = up.task
    um.destroy()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert up.state == TransferState.FAILED and w.closed
    assert um._sweep_task.cancelled() or um._sweep_task.done()
    assert um.queue("b", TWO) == DENY_NOT_SHARING


# --- rate limit -------------------------------------------------------------------

async def test_rate_limiter_caps_throughput():
    lim = RateLimiter(kbps=100, burst_bytes=0)  # 102400 B/s
    loop = asyncio.get_running_loop()
    start = loop.time()

    async def send(n):
        for _ in range(n):
            await lim.acquire(10240)

    await asyncio.gather(send(3), send(2))  # 51200 bytes shared by two uploads
    assert loop.time() - start >= 0.45


async def test_rate_limiter_zero_is_unlimited():
    lim = RateLimiter(kbps=0)
    loop = asyncio.get_running_loop()
    start = loop.time()
    for _ in range(100):
        await lim.acquire(1 << 20)
    assert loop.time() - start < 0.1


async def test_upload_respects_rate_limit(library):
    w = FakeWriter()
    um, peers = make_manager(conns={"a": (reader_with(struct.pack("<Q", 0)), w)}, kbps=1000)
    um.limiter = RateLimiter(kbps=1000, burst_bytes=0)  # ~1 MB/s, 300 KB file
    um.queue("a", TWO)
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    um.handle_transfer_response("a", peers["a"].sent[0]["token"], True)
    up = um.uploads[("a", TWO)]
    loop = asyncio.get_running_loop()
    start = loop.time()
    await wait_until(lambda: up.state == TransferState.COMPLETED)
    assert loop.time() - start >= 0.25


# --- client dispatch ---------------------------------------------------------------

def make_client(sharing=True):
    from backend.soulseek.client import SoulseekClient
    c = SoulseekClient()
    c._sharing = (sharing, time.monotonic())
    return c


async def test_client_denies_when_sharing_off(library):
    c = make_client(sharing=False)
    peer = FakePeer("alice")
    await c._handle_peer_message({"kind": "queue_upload", "filename": ONE}, peer)
    assert peer.sent == [{"kind": "upload_denied", "filename": ONE, "reason": DENY_NOT_SHARING}]
    # legacy TransferRequest(download) is refused too
    await c._handle_peer_message({"kind": "transfer_request", "direction": TransferDirection.DOWNLOAD,
                                  "token": b"\x01\x00\x00\x00", "filename": ONE}, peer)
    assert peer.sent[-1] == {"kind": "transfer_response", "token": b"\x01\x00\x00\x00",
                             "allowed": False, "reason": DENY_NOT_SHARING}
    assert c.uploads.uploads == {}
    c.destroy()


async def test_client_queues_and_answers_place_in_queue(library):
    c = make_client()
    c.uploads._kick = lambda: None
    peer = FakePeer("alice")
    await c._handle_peer_message({"kind": "queue_upload", "filename": ONE}, peer)
    await c._handle_peer_message({"kind": "queue_upload", "filename": "Nope\\x.flac"}, peer)
    await c._handle_peer_message({"kind": "transfer_request", "direction": TransferDirection.DOWNLOAD,
                                  "token": b"\x07\x00\x00\x00", "filename": THREE}, peer)
    await c._handle_peer_message({"kind": "place_in_queue_request", "filename": THREE}, peer)
    assert peer.sent == [
        {"kind": "upload_denied", "filename": "Nope\\x.flac", "reason": DENY_NOT_SHARED},
        {"kind": "transfer_response", "token": b"\x07\x00\x00\x00", "allowed": False, "reason": "Queued"},
        {"kind": "place_in_queue_response", "filename": THREE, "place": 2},
    ]
    c.destroy()


async def test_uploads_stay_out_of_the_download_keyspace(library):
    c = make_client()
    peers = {}

    async def get_peer(username):
        return peers.setdefault(username, FakePeer(username))

    c.uploads.get_peer = get_peer
    dl = c.transfers.create_transfer("alice", ONE, job_id="job-1")  # we download the same path
    c.uploads.queue("alice", ONE)
    await wait_until(lambda: "alice" in peers and peers["alice"].sent)
    up = c.uploads.uploads[("alice", ONE)]
    token = up.token
    assert c.transfers.find_transfer_by_token(token) is None
    assert c.transfers.get_transfer_by_token("alice", token) is None
    assert c.transfers.get_transfer("alice", ONE) is dl
    listed = c.transfers.get_all_transfers()
    assert sorted(t["direction"] for t in listed) == ["download", "upload"]
    # The peer's TransferResponse goes to the upload, not the download with that name
    await c._handle_peer_message({"kind": "transfer_response", "token": token,
                                  "allowed": False, "reason": "Cancelled"}, peers["alice"])
    await wait_until(lambda: up.state == TransferState.DENIED)
    assert dl.state == TransferState.REQUESTED
    c.destroy()


async def test_relayed_pierce_firewall_reaches_the_upload_not_downloads(library):
    c = make_client()
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    c._upload_relays[b"\x09\x09\x09\x09"] = fut
    r, w = reader_with(b""), FakeWriter()
    await c._handle_inbound_connection({"kind": "pierce_firewall", "token": b"\x09\x09\x09\x09"}, r, w)
    assert fut.result() == (r, w) and not w.closed
    assert c._upload_relays == {}
    c.destroy()


async def test_client_destroy_cancels_uploads(library):
    c = make_client()
    peers = {}

    async def get_peer(username):
        return peers.setdefault(username, FakePeer(username))

    c.uploads.get_peer = get_peer
    c.uploads.queue("alice", ONE)
    await wait_until(lambda: "alice" in peers and peers["alice"].sent)
    task = c.uploads.uploads[("alice", ONE)].task
    c.destroy()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert c.uploads.uploads[("alice", ONE)].state == TransferState.FAILED


# --- share list -------------------------------------------------------------------

async def test_db_entries_map_tracks_to_real_paths(tmp_path):
    music = tmp_path / "music"

    async def load():
        return [
            shares.ShareEntry("Artist/Album/01 - One.flac", 1234, 912_000, 241.6),
            shares.ShareEntry("Loose.mp3", 99, 320, None),
            shares.ShareEntry("notes.txt", 5),          # not audio: never shared
            shares.ShareEntry("../escape.flac", 10),    # never shared
        ]

    try:
        dirs, files = await shares.refresh_shares_async(str(music), True, load_entries=load)
        assert (dirs, files) == (2, 2)
        sf = shares.resolve_shared_file("Artist\\Album\\01 - One.flac")
        assert sf.real == music / "Artist" / "Album" / "01 - One.flac"
        assert sf.size == 1234
        assert sf.attrs == {FileAttribute.BITRATE: 912, FileAttribute.DURATION: 242}
        assert shares.resolve_shared_file("Loose.mp3").real == music / "Loose.mp3"
        assert shares.resolve_shared_file("notes.txt") is None
        assert shares.resolve_shared_file("..\\escape.flac") is None
        # The browse response carries the same virtual layout
        import zlib
        from backend.soulseek.protocol.parser import MessageParser
        resp = shares.get_shared_file_list_response()
        p = MessageParser(resp[4:])
        assert p.uint32() == PeerMessageCode.SHARED_FILE_LIST_RESPONSE
        inner = MessageParser(zlib.decompress(p.remaining()))
        assert inner.uint32() == 2
        assert inner.string() == ""  # root folder first (sorted)
        assert inner.uint32() == 1
        inner.uint8()
        assert inner.string() == "Loose.mp3"
        # sharing off empties the list
        assert await shares.refresh_shares_async(str(music), False, load_entries=load) == (0, 0)
        assert shares.resolve_shared_file("Loose.mp3") is None
    finally:
        shares.install(shares._empty_list())


async def test_load_db_entries_reads_the_track_table(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    import backend.database as database
    from backend.models.track import Track

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Track.__table__.create(sc))
        await conn.execute(Track.__table__.insert().values(
            id="t1", title="One", file_path="Artist/Album/01 - One.flac",
            file_size=4321, bitrate=320000, duration_seconds=200.0, disc_number=1, play_count=0,
            skip_count=0,
        ))
    monkeypatch.setattr(database, "async_session", async_sessionmaker(engine, expire_on_commit=False))
    try:
        entries = await shares.load_db_entries()
        assert entries == [shares.ShareEntry("Artist/Album/01 - One.flac", 4321, 320000, 200.0)]
        await shares.refresh_shares_async(str(tmp_path / "music"), True)
        sf = shares.resolve_shared_file("Artist\\Album\\01 - One.flac")
        assert sf.real == tmp_path / "music" / "Artist" / "Album" / "01 - One.flac"
    finally:
        shares.install(shares._empty_list())
        await engine.dispose()


async def test_empty_db_falls_back_to_filesystem(tmp_path):
    music = tmp_path / "music"
    (music / "A").mkdir(parents=True)
    (music / "A" / "x.flac").write_bytes(b"x" * 7)

    async def load():
        return []

    try:
        assert await shares.refresh_shares_async(str(music), True, load_entries=load) == (1, 1)
        assert shares.resolve_shared_file("A\\x.flac").size == 7
    finally:
        shares.install(shares._empty_list())


async def test_startup_does_not_wait_for_the_share_list(monkeypatch):
    c = make_client()
    gate = asyncio.Event()
    started = asyncio.Event()
    sent = []

    async def slow_refresh(music_dir, share_library=True, **kw):
        started.set()
        await gate.wait()
        shares.install(shares.build_share_list(music_dir, []))
        return 5, 50

    async def fake_login(username, password):
        c.server.logged_in = True
        return {"success": True}

    async def fake_send(data):
        sent.append(data)

    async def noop():
        pass

    monkeypatch.setattr(shares, "refresh_shares_async", slow_refresh)
    monkeypatch.setattr(c.server, "connect_and_login", fake_login)
    monkeypatch.setattr(c.server, "_send", fake_send)
    monkeypatch.setattr(c.listener, "start", noop)
    try:
        await asyncio.wait_for(c.connect_and_login("u", "p"), 1.0)  # returns while the list builds
        await asyncio.wait_for(started.wait(), 1.0)
        assert not sent
        gate.set()
        await wait_until(lambda: sent)  # counts reported once the list is ready
    finally:
        c.destroy()
        shares.install(shares._empty_list())


async def test_sync_refresh_inside_the_loop_only_schedules(monkeypatch, tmp_path):
    # The library scan calls the sync refresh_shares() on the event loop: it must
    # not walk the library there, just schedule the async rebuild.
    calls = []

    async def fake_async(music_dir, share_library=True, **kw):
        calls.append((music_dir, share_library))
        return 0, 0

    def boom(*a, **kw):
        raise AssertionError("walked the filesystem on the event loop")

    monkeypatch.setattr(shares, "refresh_shares_async", fake_async)
    monkeypatch.setattr(shares, "scan_filesystem_entries", boom)
    assert shares.refresh_shares(str(tmp_path), True) == shares.get_share_counts()
    await wait_until(lambda: calls)
    assert calls == [(str(tmp_path), True)]
