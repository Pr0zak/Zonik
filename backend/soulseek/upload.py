"""Upload side: serving shared library files to peers that ask for them.

Protocol (we are the uploader):
  1. The peer sends QueueUpload(filename) on the P connection (older clients send
     TransferRequest(direction=download) instead; the client treats it the same).
     The file must be in the shared list (shares.resolve_shared_file), or the
     peer gets UploadDenied. PlaceInQueueRequest is answered from our queue.
  2. When a slot is free we send TransferRequest(direction=upload, token, filename,
     size) on the P connection and wait for the peer's TransferResponse(token,
     allowed[, reason]). Not allowed with "Queued" keeps the file queued (asked
     again later); any other reason drops it.
  3. If allowed we open an F connection to the peer (the client races a direct
     PeerInit F against a server-relayed PierceFirewall), send FileTransferInit
     (the bare 4-byte token), read the 8-byte FileOffset, and stream the file
     from that offset, then wait for the peer to close.

Uploads live in their own table keyed by (username, virtual path), never in
TransferManager.transfers, so nothing on the download side — token resolution,
cancel, job progress, reputation — can see or pick one up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiofiles

from backend.soulseek.protocol.peer_messages import (
    build_file_transfer_init, build_transfer_request, build_upload_denied,
    build_upload_failed,
)
from backend.soulseek.protocol.types import TransferDirection, TransferState

log = logging.getLogger(__name__)

UPLOAD_CHUNK = 64 * 1024
RESPONSE_TIMEOUT = 60        # waiting for the peer's TransferResponse
OFFSET_TIMEOUT = 60          # waiting for FileOffset on the F connection
WRITE_TIMEOUT = 60           # one chunk not drained for this long = stalled peer
FINISH_WAIT = 30             # after the last byte, wait this long for the peer to close
QUEUED_RETRY_SECONDS = 60    # peer answered "Queued": ask again after this
# A peer that doesn't answer our TransferRequest isn't asked about any of its
# files for this long, growing with consecutive silences.
NO_ANSWER_BACKOFF = (60, 300, 1800)
TERMINAL_KEEP_SECONDS = 60   # finished entries stay visible this long
QUEUE_MAX_AGE_SECONDS = 24 * 3600  # a queued entry nobody served in a day is dropped
MAX_QUEUED_PER_USER = 200
MAX_QUEUED_BYTES_PER_USER = 20 * 1024 ** 3
MAX_QUEUED_TOTAL = 2000
SWEEP_INTERVAL = 15
DENY_CONNECT_TIMEOUT = 20    # connecting to a peer only to tell it a queued file is gone
CHANGE_THROTTLE = 0.5        # progress notifications at most this often

# Standard rejection reasons (SLSKPROTOCOL "Transfer Rejection Reasons",
# Nicotine+ slskmessages.TransferRejectReason). Clients key behaviour on the
# exact strings — e.g. Nicotine+ retries a "File not shared." with a latin-1
# path — so they must match, trailing dots included.
REASON_QUEUED = "Queued"
REASON_CANCELLED = "Cancelled"
REASON_NOT_SHARED = "File not shared."
REASON_READ_ERROR = "File read error."
REASON_SHUTDOWN = "Pending shutdown."
REASON_TOO_MANY_FILES = "Too many files"
REASON_TOO_MANY_MEGABYTES = "Too many megabytes"

TERMINAL_STATES = (TransferState.COMPLETED, TransferState.FAILED, TransferState.DENIED)


class RateLimiter:
    """Token bucket shared by every upload. Each caller takes its bytes up front
    and sleeps off any debt, so concurrent uploads together stay under the rate.
    0 = unlimited."""

    def __init__(self, kbps: int, burst_bytes: int | None = None):
        self.rate = max(0, kbps) * 1024  # bytes per second
        self.burst = burst_bytes if burst_bytes is not None else max(self.rate, UPLOAD_CHUNK)
        self.tokens = float(self.burst)
        self.last = time.monotonic()

    async def acquire(self, n: int) -> None:
        if self.rate <= 0:
            return
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
        self.last = now
        self.tokens -= n
        if self.tokens < 0:
            await asyncio.sleep(-self.tokens / self.rate)


@dataclass(eq=False)
class Upload:
    """One file a peer queued from us."""
    username: str
    filename: str          # virtual path, as the peer asked for it
    real_path: Path
    total_bytes: int
    token: bytes | None = None
    state: str = TransferState.QUEUED
    offset: int = 0        # where the peer asked us to start
    sent_bytes: int = 0    # sent on this connection (from offset)
    queued_at: float = field(default_factory=time.time)
    state_since: float = field(default_factory=time.time)
    started_at: float | None = None  # data phase began
    last_progress_at: float | None = None
    ended_at: float | None = None
    retry_at: float = 0.0  # don't ask the peer again before this (it said "Queued")
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)
    writer: Any = field(default=None, repr=False)

    @property
    def active(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(1.0, (self.offset + self.sent_bytes) / self.total_bytes)

    @property
    def speed(self) -> float:
        if not self.started_at:
            return 0.0
        elapsed = (self.ended_at or time.time()) - self.started_at
        return self.sent_bytes / elapsed if elapsed > 0 else 0.0

    @property
    def eta_seconds(self) -> float | None:
        if self.speed <= 0 or self.total_bytes <= 0:
            return None
        return max(0.0, self.total_bytes - self.offset - self.sent_bytes) / self.speed

    def to_dict(self) -> dict:
        eta = self.eta_seconds
        return {
            "direction": "upload",
            "username": self.username,
            "filename": self.filename,
            "state": self.state,
            "total_bytes": self.total_bytes,
            # Bytes moved on this transfer, under the key the stats already sum.
            "received_bytes": self.sent_bytes,
            "sent_bytes": self.sent_bytes,
            "offset": self.offset,
            "progress": round(self.progress * 100, 1),
            "speed": round(self.speed),
            "eta_seconds": round(eta) if eta is not None else None,
            "save_path": None,
            "error": self.error,
            "job_id": None,
        }


class UploadManager:
    """Queue, slots, rate cap and the data phase for uploads.

    get_peer(username) -> an object with `async send_raw(bytes)` (a PeerConnection).
    open_file_connection(username) -> (reader, writer) of a fresh F connection,
      already past PeerInit/PierceFirewall.
    resolve(virtual_path) -> shares.SharedFile | None.
    enabled() -> share_library, checked on every request, dispatch and sweep.
    send_if_connected(username, data) -> bool: write a message on an existing P
      connection without awaiting (used at shutdown); False if there is none.
    """

    def __init__(
        self,
        *,
        get_peer: Callable[[str], Awaitable[Any]],
        open_file_connection: Callable[[str], Awaitable[tuple[asyncio.StreamReader, Any]]],
        resolve: Callable[[str], Any] | None = None,
        enabled: Callable[[], bool] = lambda: True,
        slots: int = 2,
        speed_limit_kbps: int = 1024,
        on_change: Callable[[bool], Awaitable[None]] | None = None,
        send_if_connected: Callable[[str, bytes], bool] | None = None,
    ):
        if resolve is None:
            from backend.soulseek.shares import resolve_shared_file
            resolve = resolve_shared_file
        self.get_peer = get_peer
        self.open_file_connection = open_file_connection
        self.resolve = resolve
        self.enabled = enabled
        self.slots = max(1, slots)
        self.limiter = RateLimiter(speed_limit_kbps)
        self.on_change = on_change
        self.send_if_connected = send_if_connected
        self._last_change = 0.0
        self._change_task: asyncio.Task | None = None
        self._change_again = False
        # (username, virtual path) -> Upload; insertion order is queue order.
        self.uploads: dict[tuple[str, str], Upload] = {}
        # (username, token) -> future for the peer's TransferResponse.
        self._awaiting: dict[tuple[str, bytes], asyncio.Future] = {}
        # username -> (consecutive TransferResponse timeouts, don't ask before).
        self._user_backoff: dict[str, tuple[int, float]] = {}
        self._sweep_task: asyncio.Task | None = None
        # Session totals: finished entries are swept after TERMINAL_KEEP_SECONDS, so
        # anything that reports "completed"/"failed"/"bytes sent" since startup reads these.
        self.totals = {"completed": 0, "failed": 0, "bytes_sent": 0}
        self._bg: set[asyncio.Task] = set()
        self._closed = False

    def start(self) -> None:
        self._closed = False
        self._sweep_task = asyncio.create_task(self._sweep_loop())

    # --- Requests from peers ---

    def queue(self, username: str, filename: str) -> str | None:
        """A peer asked for a file. Returns None when it is queued (or already
        was), else the reason to deny it with."""
        if self._closed:
            return REASON_SHUTDOWN
        if not self.enabled():
            return REASON_NOT_SHARED
        shared = self.resolve(filename)
        if shared is None:
            log.info(f"[upload] {username} asked for an unshared file: {filename}")
            return REASON_NOT_SHARED
        key = (username, shared.virtual)
        existing = self.uploads.get(key)
        if existing is not None and existing.state not in TERMINAL_STATES:
            return None
        pending = [u for u in self.uploads.values() if u.state not in TERMINAL_STATES]
        mine = [u for u in pending if u.username == username]
        if len(pending) >= MAX_QUEUED_TOTAL or len(mine) >= MAX_QUEUED_PER_USER:
            return REASON_TOO_MANY_FILES
        if sum(u.total_bytes for u in mine) + shared.size > MAX_QUEUED_BYTES_PER_USER:
            return REASON_TOO_MANY_MEGABYTES
        self.uploads.pop(key, None)  # a finished entry for the same file goes to the back
        self.uploads[key] = Upload(
            username=username, filename=filename, real_path=shared.real, total_bytes=shared.size,
        )
        log.info(f"[upload] Queued for {username}: {filename}")
        self._kick()
        self._changed(force=True)
        return None

    def place_in_queue(self, username: str, filename: str) -> int | None:
        """1-based place among the files waiting for a slot, 0 once it is being
        served, None if we don't have it queued."""
        shared = self.resolve(filename)
        key = (username, shared.virtual if shared else filename.replace("/", "\\"))
        target = self.uploads.get(key)
        if target is None or target.state in TERMINAL_STATES:
            return None
        if target.state != TransferState.QUEUED:
            return 0
        place = 0
        for u in self.uploads.values():
            if u.state == TransferState.QUEUED:
                place += 1
            if u is target:
                return place
        return None

    def handle_transfer_response(self, username: str, token: bytes, allowed: bool, reason: str = "") -> bool:
        """The peer answered one of our upload TransferRequests. Returns False when
        the token isn't one of ours (so the download side may look at it)."""
        fut = self._awaiting.get((username, token))
        if fut is None:
            return False
        if not fut.done():
            fut.set_result((allowed, reason or ""))
        return True

    # --- Scheduling ---

    def running(self) -> int:
        return sum(1 for u in self.uploads.values() if u.active)

    def _back_off(self, username: str) -> int:
        """Record one more unanswered TransferRequest from this user; returns how
        many seconds none of their files will be offered."""
        count = self._user_backoff.get(username, (0, 0.0))[0] + 1
        wait = NO_ANSWER_BACKOFF[min(count, len(NO_ANSWER_BACKOFF)) - 1]
        self._user_backoff[username] = (count, time.time() + wait)
        return wait

    def _backed_off(self, username: str, now: float) -> bool:
        entry = self._user_backoff.get(username)
        return entry is not None and entry[1] > now

    def _kick(self) -> None:
        """Start queued uploads while slots are free: oldest first, one per peer."""
        if self._closed or not self.enabled():
            return
        now = time.time()
        free = self.slots - self.running()
        if free <= 0:
            return
        busy_users = {u.username for u in self.uploads.values() if u.active}
        for up in list(self.uploads.values()):
            if free <= 0:
                break
            if up.state != TransferState.QUEUED or up.active or up.retry_at > now:
                continue
            if up.username in busy_users or self._backed_off(up.username, now):
                continue
            busy_users.add(up.username)
            free -= 1
            up.task = asyncio.create_task(self._run(up))

    def _set_state(self, up: Upload, state: str, error: str | None = None) -> None:
        if state != up.state:
            up.state_since = time.time()
            if state in TERMINAL_STATES and up.ended_at is None:
                up.ended_at = up.state_since
                if state == TransferState.COMPLETED:
                    self.totals["completed"] += 1
                else:
                    self.totals["failed"] += 1
                self.totals["bytes_sent"] += up.sent_bytes
        up.state = state
        if error is not None:
            up.error = error

    def _changed(self, force: bool = False) -> None:
        """Tell the client something changed. Progress (not forced) is throttled
        before any task is made; forced notifications are coalesced so at most
        one is pending, plus one follow-up for changes made while it ran."""
        if self.on_change is None or self._closed:
            return
        now = time.monotonic()
        if not force and now - self._last_change < CHANGE_THROTTLE:
            return
        if self._change_task is not None and not self._change_task.done():
            self._change_again = True
            return
        self._last_change = now
        self._change_again = False
        try:
            self._change_task = asyncio.create_task(self._emit_changes(force))
        except RuntimeError:
            self._change_task = None

    async def _emit_changes(self, force: bool) -> None:
        while True:
            try:
                await self.on_change(force)
            except Exception as e:
                log.debug(f"[upload] change notification failed: {e}")
            if not self._change_again or self._closed:
                return
            # Changes arrived while that one ran: one more covers all of them.
            self._change_again = False
            force = True
            self._last_change = time.monotonic()

    def _deny(self, up: Upload, reason: str) -> None:
        """Tell the peer a file it has queued with us is not coming (UploadDenied),
        or that one already accepted broke (UploadFailed). Uses the open P
        connection when there is one; otherwise connects in the background,
        except at shutdown."""
        if up.state in (TransferState.CONNECTED, TransferState.TRANSFERRING) or up.offset or up.sent_bytes:
            data = build_upload_failed(up.filename)
        else:
            data = build_upload_denied(up.filename, reason)
        if self.send_if_connected is not None:
            try:
                if self.send_if_connected(up.username, data):
                    return
            except Exception:
                pass
        if self._closed:
            return

        async def send():
            try:
                peer = await asyncio.wait_for(self.get_peer(up.username), DENY_CONNECT_TIMEOUT)
                await peer.send_raw(data)
            except Exception as e:
                log.debug(f"[upload] Could not tell {up.username} about {up.filename}: {e}")

        task = asyncio.create_task(send())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def drop(self, up: Upload, error: str, reason: str) -> None:
        """Give up on an upload that hasn't finished: cancel it, close its socket,
        and tell the peer (`reason` is the wire string, `error` ours)."""
        if up.state in TERMINAL_STATES:
            return
        self._deny(up, reason)
        self._set_state(up, TransferState.FAILED, error)
        if up.active:
            up.task.cancel()
        _close_quietly(up.writer)
        self._changed(force=True)

    # --- One upload ---

    async def _run(self, up: Upload) -> None:
        peer = None
        accepted = False
        try:
            try:
                st = await asyncio.to_thread(up.real_path.stat)
            except OSError as e:
                self._set_state(up, TransferState.FAILED, f"File missing: {e}")
                peer = await self.get_peer(up.username)
                await peer.send_raw(build_upload_denied(up.filename, REASON_READ_ERROR))
                return
            up.total_bytes = st.st_size
            up.token = os.urandom(4)
            up.offset = up.sent_bytes = 0
            peer = await self.get_peer(up.username)

            key = (up.username, up.token)
            fut = asyncio.get_running_loop().create_future()
            self._awaiting[key] = fut
            try:
                self._set_state(up, TransferState.REQUESTED)
                await peer.send_raw(build_transfer_request(
                    TransferDirection.UPLOAD, up.token, up.filename, up.total_bytes,
                ))
                try:
                    allowed, reason = await asyncio.wait_for(fut, RESPONSE_TIMEOUT)
                except asyncio.TimeoutError:
                    # No answer: keep it queued and offer it again later (the
                    # queue age limit drops it, telling the peer, eventually).
                    # The back-off is per user, so a silent peer's other files
                    # don't take the slot one after another.
                    self._set_state(up, TransferState.QUEUED)
                    wait = self._back_off(up.username)
                    up.retry_at = time.time() + wait
                    log.info(f"[upload] {up.username} did not answer for {up.filename}; "
                             f"not asking them again for {wait} s")
                    return
            finally:
                if self._awaiting.get(key) is fut:
                    del self._awaiting[key]
            self._user_backoff.pop(up.username, None)  # it answered
            if not allowed:
                if reason.strip().rstrip(".").lower() == REASON_QUEUED.lower():
                    # The peer has it queued on its side; offer it again later.
                    self._set_state(up, TransferState.QUEUED)
                    up.retry_at = time.time() + QUEUED_RETRY_SECONDS
                    log.info(f"[upload] {up.username} has {up.filename} queued; retrying later")
                else:
                    self._set_state(up, TransferState.DENIED, reason or "Rejected by peer")
                    log.info(f"[upload] {up.username} refused {up.filename}: {reason}")
                return

            accepted = True
            self._set_state(up, TransferState.CONNECTED)
            self._changed(force=True)
            reader, writer = await self.open_file_connection(up.username)
            await self._send_file(up, reader, writer)
        except asyncio.CancelledError:
            if up.state not in TERMINAL_STATES:
                self._set_state(up, TransferState.FAILED, "Cancelled")
            _close_quietly(up.writer)
            raise
        except Exception as e:
            if up.state not in TERMINAL_STATES:
                err = "No response from peer" if isinstance(e, asyncio.TimeoutError) else (str(e) or type(e).__name__)
                self._set_state(up, TransferState.FAILED, err)
            log.warning(f"[upload] {up.username} / {up.filename} failed: {up.error}")
            if accepted and peer is not None and up.state == TransferState.FAILED:
                try:
                    await peer.send_raw(build_upload_failed(up.filename))
                except Exception:
                    pass
        finally:
            up.task = None
            self._changed(force=True)
            self._kick()

    async def _send_file(self, up: Upload, reader: asyncio.StreamReader, writer: Any) -> None:
        """FileTransferInit, FileOffset, then the bytes from that offset."""
        up.writer = writer
        try:
            writer.write(build_file_transfer_init(up.token))
            await asyncio.wait_for(writer.drain(), WRITE_TIMEOUT)
            raw = await asyncio.wait_for(reader.readexactly(8), OFFSET_TIMEOUT)
            offset = struct.unpack("<Q", raw)[0]
            if offset > up.total_bytes:
                raise ValueError(f"Offset {offset} past end of file ({up.total_bytes})")
            up.offset = offset
            up.started_at = up.last_progress_at = time.time()
            self._set_state(up, TransferState.TRANSFERRING)
            log.info(f"[upload] Sending {up.filename} to {up.username} from offset {offset}")
            remaining = up.total_bytes - offset
            async with aiofiles.open(up.real_path, "rb") as f:
                if offset:
                    await f.seek(offset)
                while remaining > 0:
                    chunk = await f.read(min(UPLOAD_CHUNK, remaining))
                    if not chunk:
                        break
                    await self.limiter.acquire(len(chunk))
                    writer.write(chunk)
                    await asyncio.wait_for(writer.drain(), WRITE_TIMEOUT)
                    up.sent_bytes += len(chunk)
                    remaining -= len(chunk)
                    up.last_progress_at = time.time()
                    self._changed()
            if remaining > 0:
                raise IOError(f"File shrank: sent {up.sent_bytes}/{up.total_bytes - offset}")
            # Let the downloader close first so the tail isn't cut off by our close.
            try:
                await asyncio.wait_for(_drain_until_eof(reader), FINISH_WAIT)
            except (asyncio.TimeoutError, ConnectionError, OSError):
                pass
            self._set_state(up, TransferState.COMPLETED)
            log.info(f"[upload] Completed {up.filename} to {up.username} ({up.sent_bytes} bytes)")
        finally:
            up.writer = None
            _close_quietly(writer)

    # --- Housekeeping ---

    async def _sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(SWEEP_INTERVAL)
                self._sweep(time.time())
        except asyncio.CancelledError:
            return

    def _sweep(self, now: float) -> None:
        enabled = self.enabled()
        pruned = False
        for key, up in list(self.uploads.items()):
            if up.state in TERMINAL_STATES:
                if now - (up.ended_at or up.queued_at) > TERMINAL_KEEP_SECONDS:
                    del self.uploads[key]
                    pruned = True
            elif not enabled:
                self.drop(up, "Sharing turned off", REASON_NOT_SHARED)
            elif up.state == TransferState.QUEUED and not up.active and now - up.queued_at > QUEUE_MAX_AGE_SECONDS:
                self.drop(up, "Queue timeout", REASON_CANCELLED)
        if pruned:
            self._changed(force=True)  # finished rows leave the UI's list too
        waiting = self.active_usernames()
        for user, (_, until) in list(self._user_backoff.items()):
            if user not in waiting and until <= time.time():
                del self._user_backoff[user]
        self._kick()

    def get_all(self) -> list[dict]:
        return [u.to_dict() for u in self.uploads.values()]

    def active_usernames(self) -> set[str]:
        return {u.username for u in self.uploads.values() if u.state not in TERMINAL_STATES}

    def destroy(self) -> None:
        self._closed = True
        if self._sweep_task and not self._sweep_task.done():
            self._sweep_task.cancel()
        # _closed is set, so drop() only tells peers over connections already open.
        for up in list(self.uploads.values()):
            self.drop(up, "Shutting down", REASON_SHUTDOWN)
        for fut in self._awaiting.values():
            if not fut.done():
                fut.cancel()
        self._awaiting.clear()
        for task in list(self._bg):
            task.cancel()


async def _drain_until_eof(reader: asyncio.StreamReader) -> None:
    while await reader.read(4096):
        pass


def _close_quietly(writer: Any) -> None:
    if writer is None:
        return
    try:
        writer.close()
    except Exception:
        pass
