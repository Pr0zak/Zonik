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
    REASON_NOT_SHARED, REASON_SHUTDOWN, RateLimiter, UploadManager,
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
    assert um.queue("eve", "..\\secret.flac") == REASON_NOT_SHARED
    assert um.queue("eve", str(secret)) == REASON_NOT_SHARED
    assert um.queue("eve", "Artist\\Album\\nope.flac") == REASON_NOT_SHARED
    assert um.uploads == {}


async def test_sharing_off_denies_everything(library):
    um, _ = make_manager(enabled=False)
    assert um.queue("alice", ONE) == REASON_NOT_SHARED
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


async def test_no_transfer_response_requeues(library, monkeypatch):
    import backend.soulseek.upload as upload_mod
    monkeypatch.setattr(upload_mod, "RESPONSE_TIMEOUT", 0.05)
    um, peers = make_manager()
    um.queue("a", ONE)
    up = um.uploads[("a", ONE)]
    await wait_until(lambda: "a" in peers and peers["a"].sent)
    await wait_until(lambda: not up.active)
    assert up.state == TransferState.QUEUED and up.retry_at > time.time()


async def test_dropped_queued_upload_is_denied_to_the_peer(library):
    um, peers = make_manager()
    um._kick = lambda: None
    um.queue("a", ONE)
    up = um.uploads[("a", ONE)]
    up.queued_at -= 2 * 24 * 3600
    um._sweep(time.time())
    assert up.state == TransferState.FAILED and up.error == "Queue timeout"
    m = await (await um.get_peer("a")).wait_for("upload_denied")
    assert m == {"kind": "upload_denied", "filename": ONE, "reason": "Cancelled"}


async def test_sharing_turned_off_denies_queued_uploads(library):
    flag = {"on": True}
    um, peers = make_manager()
    um.enabled = lambda: flag["on"]
    um._kick = lambda: None
    um.queue("a", ONE)
    flag["on"] = False
    um._sweep(time.time())
    m = await (await um.get_peer("a")).wait_for("upload_denied")
    assert m["reason"] == "File not shared."
    assert um.uploads[("a", ONE)].state == TransferState.FAILED


async def test_shutdown_tells_connected_peers(library):
    sent = []
    um, peers = make_manager()
    um.send_if_connected = lambda user, data: sent.append((user, parse_peer_message(data[4:]))) or True
    um._kick = lambda: None
    um.queue("a", ONE)
    um.destroy()
    assert sent == [("a", {"kind": "upload_denied", "filename": ONE, "reason": REASON_SHUTDOWN})]
    assert um.queue("b", TWO) == REASON_SHUTDOWN


async def test_missing_file_is_a_read_error(library):
    music, _ = library
    um, peers = make_manager()
    um.queue("a", ONE)
    (music / "Artist" / "Album" / "01 - One.flac").unlink()
    # the queue entry exists already; its _run stats the file
    m = await (await um.get_peer("a")).wait_for("upload_denied")
    assert m["reason"] == "File read error."


async def test_change_notifications_are_throttled_and_coalesced(library):
    calls = []
    gate = asyncio.Event()

    async def on_change(force):
        calls.append(force)
        await gate.wait()

    um, _ = make_manager()
    um.on_change = on_change
    for _ in range(50):
        um._changed()          # progress: one notification, the rest throttled
    um._changed(force=True)    # pending one running: coalesced
    um._changed(force=True)
    await asyncio.sleep(0.01)
    assert calls == [False]
    gate.set()
    await wait_until(lambda: len(calls) == 2)
    await asyncio.sleep(0.05)
    assert calls == [False, True]


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
    assert um.queue("b", TWO) == REASON_SHUTDOWN


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
    assert peer.sent == [{"kind": "upload_denied", "filename": ONE, "reason": REASON_NOT_SHARED}]
    # legacy TransferRequest(download) is refused too
    await c._handle_peer_message({"kind": "transfer_request", "direction": TransferDirection.DOWNLOAD,
                                  "token": b"\x01\x00\x00\x00", "filename": ONE}, peer)
    assert peer.sent[-1] == {"kind": "transfer_response", "token": b"\x01\x00\x00\x00",
                             "allowed": False, "reason": REASON_NOT_SHARED}
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
        {"kind": "upload_denied", "filename": "Nope\\x.flac", "reason": REASON_NOT_SHARED},
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
    assert [t["direction"] for t in c.transfers.get_all_transfers()] == ["download"]
    assert [t["direction"] for t in c.transfers.get_active_transfers()] == ["download"]
    assert [t["direction"] for t in c.transfers.get_all_uploads()] == ["upload"]
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


# --- wire layouts, from the spec (not from our own builders) ----------------------

def _u32(v):
    return struct.pack("<I", v)


def _str(s):
    b = s.encode()
    return _u32(len(b)) + b


def _parse_browse(resp):
    """Read a SharedFileListResponse the way a client does (Peer Code 5)."""
    import zlib
    from backend.soulseek.protocol.parser import MessageParser
    p = MessageParser(resp[4:])
    assert p.uint32() == PeerMessageCode.SHARED_FILE_LIST_RESPONSE
    raw = zlib.decompress(p.remaining())
    inner = MessageParser(raw)
    folders = []
    for _ in range(inner.uint32()):
        folder = inner.string()
        files = []
        for _ in range(inner.uint32()):
            assert inner.uint8() == 1
            name = inner.string()
            size = inner.uint64()
            inner.string()  # extension
            for _ in range(inner.uint32()):
                inner.uint32(), inner.uint32()
            files.append((name, size))
        folders.append((folder, files))
    assert inner.uint32() == 0  # unknown
    assert inner.uint32() == 0  # private folders
    assert not inner.has_remaining()
    return raw, folders


async def test_browse_paths_resolve_the_way_clients_build_them(tmp_path):
    music = tmp_path / "music"
    entries = [
        shares.ShareEntry("Artist/Album/01 - One.flac", 10),
        shares.ShareEntry("Loose.mp3", 20),
    ]
    try:
        shares.install(shares.build_share_list(str(music), entries))
        _, folders = _parse_browse(shares.get_shared_file_list_response())
        assert folders == [("", [("Loose.mp3", 20)]), ("Artist\\Album", [("01 - One.flac", 10)])]
        # Nicotine+ userbrowse: download path = folder + "\\" + name
        requested = {folder + "\\" + name for folder, files in folders for name, _ in files}
        assert requested == {"\\Loose.mp3", "Artist\\Album\\01 - One.flac"}
        assert shares.resolve_shared_file("\\Loose.mp3").real == music / "Loose.mp3"
        assert shares.resolve_shared_file("Artist\\Album\\01 - One.flac").real == \
            music / "Artist" / "Album" / "01 - One.flac"
        # and the upload side queues exactly those names
        um, _ = make_manager()
        um._kick = lambda: None
        for path in requested:
            assert um.queue("peer", path) is None
    finally:
        shares.install(shares._empty_list())


async def test_browse_list_bytes_match_the_spec(tmp_path):
    entries = [shares.ShareEntry("Artist/Album/01 - One.flac", 1000, 900_000, 60.4)]
    expected = (
        _u32(1)                                   # folders
        + _str("Artist\\Album") + _u32(1)         # folder, file count
        + b"\x01" + _str("01 - One.flac")         # code, bare file name
        + struct.pack("<Q", 1000) + _str("flac")  # size, extension
        + _u32(2) + _u32(0) + _u32(900) + _u32(1) + _u32(60)  # bitrate, length
        + _u32(0)                                 # unknown
        + _u32(0)                                 # private folders
    )
    try:
        shares.install(shares.build_share_list(str(tmp_path), entries))
        raw, _ = _parse_browse(shares.get_shared_file_list_response())
        assert raw == expected
        empty, folders = _parse_browse(shares._empty_list().response)
        assert empty == _u32(0) + _u32(0) + _u32(0) and folders == []
    finally:
        shares.install(shares._empty_list())


async def test_transfer_response_bytes_from_the_spec():
    token = b"\x05\x00\x00\x00"
    allowed_with_size = _u32(41) + token + b"\x01" + struct.pack("<Q", 123456)
    assert parse_peer_message(allowed_with_size) == {
        "kind": "transfer_response", "token": token, "allowed": True, "size": 123456}
    allowed_bare = _u32(41) + token + b"\x01"
    assert parse_peer_message(allowed_bare) == {"kind": "transfer_response", "token": token, "allowed": True}
    refused = _u32(41) + token + b"\x00" + _str("Queued")
    assert parse_peer_message(refused) == {
        "kind": "transfer_response", "token": token, "allowed": False, "reason": "Queued"}
    refused_bare = _u32(41) + token + b"\x00"
    assert parse_peer_message(refused_bare)["reason"] == ""


async def test_upload_side_message_bytes_from_the_spec():
    from backend.soulseek.protocol.peer_messages import (
        build_place_in_queue_response, build_transfer_request, build_upload_failed,
        build_file_transfer_init,
    )
    token = b"\x07\x00\x00\x00"
    body = _u32(40) + _u32(1) + token + _str("A\\b.flac") + struct.pack("<Q", 99)
    assert build_transfer_request(TransferDirection.UPLOAD, token, "A\\b.flac", 99) == _u32(len(body)) + body
    body = _u32(44) + _str("A\\b.flac") + _u32(3)
    assert build_place_in_queue_response("A\\b.flac", 3) == _u32(len(body)) + body
    body = _u32(46) + _str("A\\b.flac")
    assert build_upload_failed("A\\b.flac") == _u32(len(body)) + body
    assert build_file_transfer_init(token) == token


# --- client plumbing ----------------------------------------------------------------

async def test_sharing_flip_wakes_the_refresh_loop(monkeypatch):
    import backend.soulseek.client as client_mod
    import backend.config as config
    c = make_client(sharing=False)
    refreshes = []

    async def fake_refresh():
        refreshes.append(c._sharing[0])
        return 0, 0

    monkeypatch.setattr(c, "refresh_shares", fake_refresh)
    task = asyncio.create_task(c._share_refresh_loop())
    try:
        await wait_until(lambda: len(refreshes) == 1)
        real = config.get_settings()
        on = real.model_copy(update={"soulseek": real.soulseek.model_copy(update={"share_library": True})})
        monkeypatch.setattr(config, "get_settings", lambda: on)
        c._sharing = (False, time.monotonic() - client_mod.SHARING_CHECK_SECONDS - 1)
        assert c._sharing_enabled() is True
        await wait_until(lambda: len(refreshes) == 2)  # not 6 h later
    finally:
        task.cancel()
        c.destroy()


async def test_concurrent_peer_address_requests_all_get_the_answer(monkeypatch):
    c = make_client()

    async def fake_get(username):
        pass

    monkeypatch.setattr(c.server, "get_peer_address", fake_get)
    a = asyncio.create_task(c._request_peer_address("bob", timeout=1))
    b = asyncio.create_task(c._request_peer_address("bob", timeout=1))
    await wait_until(lambda: len(c._peer_address_futures.get("bob", [])) == 2)
    await c._handle_server_message({"kind": "get_peer_address", "username": "bob", "host": "h", "port": 7})
    assert await a == await b == {"host": "h", "port": 7}
    assert "bob" not in c._peer_address_futures
    c.destroy()


async def test_failed_login_tears_everything_down(monkeypatch):
    c = make_client()

    async def bad_login(username, password):
        raise ConnectionError("Login failed: INVALIDPASS")

    async def noop():
        pass

    monkeypatch.setattr(c.server, "connect_and_login", bad_login)
    monkeypatch.setattr(c.listener, "start", noop)
    with pytest.raises(ConnectionError):
        await c.connect_and_login("u", "p")
    await asyncio.sleep(0)
    assert c.uploads._sweep_task.done()
    assert c._peer_cleanup_task.done()
    assert c.transfers._cleanup_task.done()


async def test_silent_peer_does_not_hold_the_slot(library, monkeypatch):
    import backend.soulseek.upload as upload_mod
    monkeypatch.setattr(upload_mod, "RESPONSE_TIMEOUT", 0.05)
    um, peers = make_manager(slots=1)
    for f in (ONE, TWO, THREE):
        assert um.queue("silent", f) is None
    assert um.queue("other", ONE) is None
    # silent's first file times out, then the slot goes to the other peer
    await wait_until(lambda: "other" in peers and peers["other"].sent)
    req = peers["other"].sent[0]
    um.handle_transfer_response("other", req["token"], False, "Cancelled")  # it answers
    await asyncio.sleep(0.3)  # several response timeouts' worth
    asked = [m for m in peers["silent"].sent if m["kind"] == "transfer_request"]
    assert len(asked) == 1  # its other files were not tried one after another
    assert um.running() == 0
    assert um._user_backoff["silent"][0] == 1
    assert "other" not in um._user_backoff
    # the back-off grows with consecutive silences
    assert [um._back_off("x") for _ in range(4)] == [60, 300, 1800, 1800]


async def test_flip_during_a_refresh_is_not_lost(monkeypatch):
    c = make_client(sharing=False)
    refreshes = []

    async def fake_refresh():
        refreshes.append(1)
        if len(refreshes) == 1:
            c._share_wake.set()  # share_library flip noticed while this refresh runs
        return 0, 0

    monkeypatch.setattr(c, "refresh_shares", fake_refresh)
    task = asyncio.create_task(c._share_refresh_loop())
    try:
        await wait_until(lambda: len(refreshes) >= 2, timeout=1.0)
    finally:
        task.cancel()
        c.destroy()


async def test_cancelled_peer_connect_stops_both_attempts(monkeypatch):
    c = make_client()
    started = []

    async def slow_address(username, timeout=10):
        started.append("direct")
        await asyncio.sleep(10)

    async def noop(*a):
        pass

    monkeypatch.setattr(c, "_request_peer_address", slow_address)
    monkeypatch.setattr(c.server, "connect_to_peer", noop)
    original = c.listener.on_connection
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(c._get_or_connect_peer("bob"), 0.05)
    await asyncio.sleep(0.01)
    assert started == ["direct"]
    assert c.listener.on_connection == original  # the indirect attempt was unwound too
    assert "bob" not in c.peers
    c.destroy()
