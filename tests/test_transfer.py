"""TransferManager file-connection handling, without sockets or a database.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_transfer.py
"""
import asyncio
import struct
from pathlib import Path

import pytest

from backend.soulseek.protocol.types import TransferState
from backend.soulseek.transfer import TransferManager

pytestmark = pytest.mark.asyncio


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


def make_manager(tmp_path):
    calls = []

    async def on_complete(t):
        calls.append((t, t.state))

    tm = TransferManager(staging_dir=str(tmp_path / "staging"), on_complete=on_complete)
    return tm, calls


def make_transfer(tm, filename="Music\\Artist\\01 - Song.flac", total=0, token=b"\x01\x02\x03\x04",
                  username="peer", job_id="job-1"):
    t = tm.create_transfer(username, filename, job_id=job_id)
    t.token = token
    t.total_bytes = total
    t.state = TransferState.CONNECTED
    return t


def reader_with(data: bytes, eof: bool = True) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(data)
    if eof:
        r.feed_eof()
    return r


async def wait_for_state(t, *states, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while t.state not in states:
        if loop.time() > end:
            raise AssertionError(f"state stayed {t.state}")
        await asyncio.sleep(0.01)


# --- _receive ---------------------------------------------------------------

async def test_receive_exact_size_completes(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=1000)
    w = FakeWriter()
    await tm._receive(t, reader_with(b"a" * 1000), w)
    assert t.state == TransferState.COMPLETED
    assert Path(t.save_path).read_bytes() == b"a" * 1000
    assert bytes(w.data) == struct.pack("<Q", 0)  # offset sent
    assert w.closed
    assert len(calls) == 1
    # staged under <staging>/<job>/<token hex>/<basename>
    assert Path(t.save_path) == tmp_path / "staging" / "job-1" / "01020304" / "01 - Song.flac"


async def test_receive_unknown_size_eof_completes(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=0)
    await tm._receive(t, reader_with(b"b" * 500), FakeWriter())
    assert t.state == TransferState.COMPLETED
    assert t.received_bytes == 500
    assert len(calls) == 1


async def test_receive_no_data_fails(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=1000)
    await tm._receive(t, reader_with(b""), FakeWriter())
    assert t.state == TransferState.FAILED
    assert len(calls) == 1


async def test_receive_refuses_terminal_transfer(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=10)
    t.state = TransferState.FAILED
    w = FakeWriter()
    await tm._receive(t, reader_with(b"x" * 10), w)
    assert w.closed and not w.data
    assert t.save_path is None
    assert calls == []


# --- abort ------------------------------------------------------------------

async def test_abort_cancels_task_and_removes_partial(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=1000)
    reader = reader_with(b"c" * 100, eof=False)  # peer keeps the socket open
    w = FakeWriter()
    task = asyncio.create_task(tm._receive(t, reader, w))
    t.task = task
    loop = asyncio.get_running_loop()
    end = loop.time() + 2
    while t.received_bytes < 100:
        assert loop.time() < end
        await asyncio.sleep(0.01)
    partial = Path(t.save_path)
    assert partial.exists()

    assert tm.abort(t, "Stalled (no data)") is True
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)  # let the scheduled on_complete run
    assert t.state == TransferState.FAILED and t.error == "Stalled (no data)"
    assert w.closed
    assert not partial.exists()
    assert not tm.is_tracked(t)
    assert len(calls) == 1  # once, even though both abort and the handler finished it


async def test_abort_without_task_notifies_once(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm)
    t.state = TransferState.QUEUED
    tm.abort(t, "Peer did not respond")
    tm.abort(t, "again")
    await asyncio.sleep(0)
    assert t.state == TransferState.FAILED and t.error == "Peer did not respond"
    assert len(calls) == 1


async def test_abort_leaves_completed_transfer_alone(tmp_path):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=3)
    await tm._receive(t, reader_with(b"xyz"), FakeWriter())
    assert tm.abort(t, "late") is False
    assert Path(t.save_path).exists()
    assert t.state == TransferState.COMPLETED


async def test_abort_blame_peer_flag(tmp_path):
    tm, _ = make_manager(tmp_path)
    t = make_transfer(tm)
    tm.abort(t, "Cancelled by user", blame_peer=False)
    assert t.blame_peer is False


async def test_discard_job_removes_staging_folder(tmp_path):
    tm, _ = make_manager(tmp_path)
    t = make_transfer(tm, total=3)
    await tm._receive(t, reader_with(b"xyz"), FakeWriter())
    folder = tmp_path / "staging" / "job-1"
    assert folder.exists()
    tm.discard_job("job-1")
    assert not folder.exists()


# --- token re-resolution ------------------------------------------------------

def two_queued(tm):
    a = make_transfer(tm, filename="Music\\A.flac", total=4, token=b"\x01\x00\x00\x00")
    b = make_transfer(tm, filename="Music\\B.flac", total=6, token=b"\x02\x00\x00\x00")
    return a, b


async def test_inbound_connection_switches_to_token_named_transfer(tmp_path):
    tm, calls = make_manager(tmp_path)
    a, b = two_queued(tm)
    relay = b"\xff\xff\xff\xff"  # server relay token: matches nothing, so the pick is by username
    assert tm.find_active_transfer_for_user("peer") is a
    w = FakeWriter()
    await tm.handle_file_transfer_connection("peer", relay, reader_with(b"\x02\x00\x00\x00" + b"BBBBBB"), w)
    assert b.state == TransferState.COMPLETED
    assert Path(b.save_path).name == "B.flac" and Path(b.save_path).read_bytes() == b"BBBBBB"
    assert a.state == TransferState.CONNECTED and a.save_path is None
    assert [t for t, _ in calls] == [b]


async def test_outbound_connection_switches_to_token_named_transfer(tmp_path, monkeypatch):
    tm, _ = make_manager(tmp_path)
    a, b = two_queued(tm)
    w = FakeWriter()

    async def fake_open(host, port):
        return reader_with(b"\x02\x00\x00\x00" + b"BBBBBB"), w

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    await tm.handle_outbound_file_transfer(a, "h", 1, b"\xff\xff\xff\xff", matched_by_token=False)
    assert b.state == TransferState.COMPLETED and a.state == TransferState.CONNECTED


async def test_connection_for_transfer_already_streaming_is_closed(tmp_path):
    tm, calls = make_manager(tmp_path)
    a, b = two_queued(tm)
    b.state = TransferState.TRANSFERRING
    other = asyncio.create_task(asyncio.sleep(10))  # the connection already streaming B
    b.task = other
    try:
        w = FakeWriter()
        await tm.handle_file_transfer_connection("peer", b"\xff" * 4, reader_with(b"\x02\x00\x00\x00" + b"BBBBBB"), w)
        assert w.closed and not w.data  # no offset sent, nothing written
        assert b.task is other and b.save_path is None
        assert calls == []
    finally:
        other.cancel()


async def test_unknown_token_does_not_write_under_provisional_name(tmp_path):
    tm, calls = make_manager(tmp_path)
    a, b = two_queued(tm)
    w = FakeWriter()
    await tm.handle_file_transfer_connection("peer", b"\xff" * 4, reader_with(b"\x09\x00\x00\x00" + b"ZZZZ"), w)
    assert w.closed and not w.data
    assert a.state == TransferState.CONNECTED and a.save_path is None
    assert calls == []


async def test_cross_user_token_collision_is_ignored(tmp_path):
    tm, _ = make_manager(tmp_path)
    mine = make_transfer(tm, filename="Music\\Mine.flac", total=4, token=None, username="peer")
    theirs = make_transfer(tm, filename="Music\\Theirs.flac", total=4, token=b"\x02\x00\x00\x00", username="other")
    await tm.handle_file_transfer_connection("peer", b"\xff" * 4, reader_with(b"\x02\x00\x00\x00" + b"MMMM"), FakeWriter())
    assert theirs.state == TransferState.CONNECTED and theirs.save_path is None
    assert mine.state == TransferState.COMPLETED


# --- cleanup sweep ------------------------------------------------------------

async def test_sweep_ages_transferring_from_last_progress(tmp_path):
    tm, calls = make_manager(tmp_path)
    tm.max_transfer_seconds = 1800
    now = 10_000.0
    slow = make_transfer(tm, filename="Music\\slow.flac", token=b"\x01\x00\x00\x00")
    slow.state = TransferState.TRANSFERRING
    slow.started_at = now - 3600          # an hour old...
    slow.last_progress_at = now - 30      # ...but still receiving
    dead = make_transfer(tm, filename="Music\\dead.flac", token=b"\x02\x00\x00\x00")
    dead.state = TransferState.TRANSFERRING
    dead.started_at = now - 3600
    dead.last_progress_at = now - 1801
    tm._sweep(now)
    await asyncio.sleep(0)
    assert slow.state == TransferState.TRANSFERRING and tm.is_tracked(slow)
    assert dead.state == TransferState.FAILED and not tm.is_tracked(dead)
    assert [t for t, _ in calls] == [dead]


async def test_sweep_keeps_terminal_entries_for_a_minute(tmp_path):
    tm, _ = make_manager(tmp_path)
    now = 10_000.0
    t = make_transfer(tm)
    t.started_at = now - 3600
    t.state = TransferState.COMPLETED
    t.ended_at = now - 30
    tm._sweep(now)
    assert tm.is_tracked(t)
    tm._sweep(now + 31)
    assert not tm.is_tracked(t)


# --- 100 % or nothing -----------------------------------------------------------

@pytest.mark.parametrize("got", [0, 500, 990, 999])
async def test_short_file_fails_and_partial_is_removed(tmp_path, got):
    tm, calls = make_manager(tmp_path)
    t = make_transfer(tm, total=1000)
    await tm._receive(t, reader_with(b"d" * got), FakeWriter())
    assert t.state == TransferState.FAILED
    assert t.error == ("No data received" if got == 0 else f"Incomplete: {got}/1000")
    assert not Path(t.save_path).exists()
    assert len(calls) == 1


async def test_stall_near_the_end_fails(tmp_path):
    tm, _ = make_manager(tmp_path)
    tm.read_timeout = 0.05
    t = make_transfer(tm, total=1000)
    await tm._receive(t, reader_with(b"e" * 999, eof=False), FakeWriter())
    assert t.state == TransferState.FAILED and t.error == "Incomplete: 999/1000"
    assert not Path(t.save_path).exists()


async def test_stall_with_unknown_size_fails(tmp_path):
    tm, _ = make_manager(tmp_path)
    tm.read_timeout = 0.05
    t = make_transfer(tm, total=0)
    await tm._receive(t, reader_with(b"f" * 10, eof=False), FakeWriter())
    assert t.state == TransferState.FAILED
