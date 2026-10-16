"""Download transfer state machine and file I/O."""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Awaitable

import aiofiles

from backend.soulseek.protocol.peer_messages import build_pierce_firewall_raw
from backend.soulseek.protocol.types import TransferState

log = logging.getLogger(__name__)

DOWNLOAD_TTL = 5 * 60  # 5 minutes

ACTIVE_STATES = (
    TransferState.REQUESTED, TransferState.QUEUED,
    TransferState.CONNECTED, TransferState.TRANSFERRING,
)

TERMINAL_STATES = (TransferState.COMPLETED, TransferState.FAILED, TransferState.DENIED)

_SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(eq=False)  # identity semantics: two transfers are never "equal"
class Transfer:
    """Represents a single file download."""
    username: str
    filename: str
    token: bytes | None = None
    state: str = TransferState.REQUESTED
    total_bytes: int = 0
    received_bytes: int = 0
    started_at: float = field(default_factory=time.time)
    save_path: str | None = None
    error: str | None = None
    job_id: str | None = None  # links transfer back to the originating Job
    # The running file-connection handler and its socket, so a give-up can stop it.
    task: asyncio.Task | None = field(default=None, repr=False)
    writer: asyncio.StreamWriter | None = field(default=None, repr=False)
    # False when the failure is ours (user cancel, another source won), not the peer's.
    blame_peer: bool = True
    notified: bool = False  # on_complete has fired (it must fire exactly once)

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return self.received_bytes / self.total_bytes

    @property
    def speed(self) -> float:
        """Bytes per second."""
        elapsed = time.time() - self.started_at
        if elapsed <= 0:
            return 0.0
        return self.received_bytes / elapsed

    @property
    def eta_seconds(self) -> float | None:
        """Estimated seconds remaining."""
        if self.speed <= 0 or self.total_bytes <= 0:
            return None
        remaining = self.total_bytes - self.received_bytes
        if remaining <= 0:
            return 0.0
        return remaining / self.speed

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "filename": self.filename,
            "state": self.state,
            "total_bytes": self.total_bytes,
            "received_bytes": self.received_bytes,
            "progress": round(self.progress * 100, 1),
            "speed": round(self.speed),
            "eta_seconds": round(self.eta_seconds) if self.eta_seconds is not None else None,
            "save_path": self.save_path,
            "error": self.error,
            "job_id": self.job_id,
        }


class TransferManager:
    """Manages active file transfers."""

    def __init__(
        self,
        staging_dir: str = "/opt/zonik/cache/staging",
        on_progress: Callable[[Transfer], Awaitable[None]] | None = None,
        on_complete: Callable[[Transfer], Awaitable[None]] | None = None,
    ):
        # Transfers are staged on local disk, one folder per job, and the
        # importer moves the finished file into the library. Nothing is written
        # to the NAS download dir any more.
        self.staging_dir = staging_dir
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.transfers: dict[str, Transfer] = {}  # keyed by "username:filename"
        self._cleanup_task: asyncio.Task | None = None
        self._bg: set[asyncio.Task] = set()  # on_complete calls scheduled by abort()

    def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    @staticmethod
    def _normalize_key(username: str, filename: str) -> str:
        """Normalize transfer key — canonicalize path separators."""
        return f"{username}:{filename.replace(chr(92), '/')}"

    def get_transfer(self, username: str, filename: str, expected_size: int = 0) -> Transfer | None:
        # Exact match first (normalized)
        t = self.transfers.get(self._normalize_key(username, filename))
        if t:
            return t
        # Fuzzy fallback: match by username + basename + optional size check
        basename = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
        for t in self.transfers.values():
            if t.username == username and t.state in ("requested", "queued", "connected"):
                t_basename = t.filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
                if t_basename == basename:
                    # If both sides have size info, verify they match (within 1MB tolerance)
                    if expected_size > 0 and t.total_bytes > 0:
                        if abs(t.total_bytes - expected_size) > 1024 * 1024:
                            continue  # Size mismatch, probably different file
                    return t
        return None

    def get_transfer_by_token(self, username: str, token: bytes) -> Transfer | None:
        for t in self.transfers.values():
            if t.username == username and t.token == token:
                return t
        return None

    def find_transfer_by_token(self, token: bytes) -> Transfer | None:
        """Find a transfer by token only (no username required). Used for inbound pierce_firewall."""
        for t in self.transfers.values():
            if t.token == token and t.state in (TransferState.CONNECTED, TransferState.REQUESTED, TransferState.QUEUED):
                return t
        return None

    def find_active_transfer_for_user(self, username: str) -> Transfer | None:
        """Find an active (CONNECTED) transfer for a user. Used for server-mediated file transfers
        where the relay token differs from the transfer token."""
        # Prefer CONNECTED state (just accepted TRANSFER_REQUEST)
        for t in self.transfers.values():
            if t.username == username and t.state == TransferState.CONNECTED:
                return t
        # Fall back to QUEUED/REQUESTED
        for t in self.transfers.values():
            if t.username == username and t.state in (TransferState.REQUESTED, TransferState.QUEUED):
                return t
        return None

    def create_transfer(self, username: str, filename: str, job_id: str | None = None) -> Transfer:
        key = self._normalize_key(username, filename)
        transfer = Transfer(username=username, filename=filename, job_id=job_id)
        self.transfers[key] = transfer
        return transfer

    def is_tracked(self, transfer: Transfer) -> bool:
        """Is this exact Transfer object still in the table (not dropped or replaced)?"""
        return self.transfers.get(self._normalize_key(transfer.username, transfer.filename)) is transfer

    def remove_transfer(self, username: str, filename: str) -> None:
        self.transfers.pop(self._normalize_key(username, filename), None)

    def job_dir(self, job_id: str) -> Path | None:
        """The staging folder for one job, or None if the id isn't a safe folder name."""
        if not job_id or not _SAFE_NAME.fullmatch(job_id):
            return None
        return Path(self.staging_dir) / job_id

    def save_path_for(self, transfer: Transfer) -> Path:
        """<staging_dir>/<job_id>/<token hex>/<basename> (or <token hex>/<basename>
        without a job). The token level keeps two sources of one job that share a
        basename — scene releases usually do — from writing into the same file."""
        basename = transfer.filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if basename in ("", ".", ".."):
            basename = "download"
        tok = transfer.token.hex() if transfer.token else f"t{id(transfer):x}"
        base = self.job_dir(transfer.job_id) if transfer.job_id else None
        if base is None:
            base = Path(self.staging_dir)
        return base / tok / basename

    def discard_job(self, job_id: str) -> None:
        """Remove a finished job's staging folder (after it imported or rejected its file).
        Any transfer of that job still in flight is an orphan by now — abort it first."""
        for t in list(self.transfers.values()):
            if t.job_id == job_id and t.state in ACTIVE_STATES:
                self.abort(t, "Job finished", blame_peer=False)
        folder = self.job_dir(job_id)
        if folder is None or not folder.exists():
            return
        try:
            shutil.rmtree(folder)
        except OSError as e:
            log.warning(f"[transfer] Could not remove staging folder {folder}: {e}")

    def update_state(self, transfer: Transfer, state: str, **kwargs) -> None:
        transfer.state = state
        for k, v in kwargs.items():
            setattr(transfer, k, v)

    # --- Giving up, and firing on_complete exactly once ---

    def abort(self, transfer: Transfer, error: str, *, blame_peer: bool = True) -> bool:
        """Give up on a transfer: mark it FAILED, cancel its handler task, close its
        socket, delete the partial file, drop it from the table and fire on_complete
        (once). blame_peer=False when the give-up is ours (user cancel, another
        source won) so the peer's reputation isn't charged for it.

        A COMPLETED transfer is left alone (its file is about to be imported);
        returns False in that case, True otherwise."""
        if transfer.state == TransferState.COMPLETED:
            return False
        if not blame_peer:
            transfer.blame_peer = False
        if transfer.state not in TERMINAL_STATES:
            self.update_state(transfer, TransferState.FAILED, error=error)
        task = transfer.task
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        if task is not None and not task.done() and task is not current:
            task.cancel()
        self._close_writer(transfer)
        self._remove_partial(transfer)
        self._forget(transfer)
        self._schedule_notify(transfer)
        log.info(f"[transfer] Aborted {transfer.username} / {transfer.filename}: {error}")
        return True

    def _forget(self, transfer: Transfer) -> None:
        key = self._normalize_key(transfer.username, transfer.filename)
        if self.transfers.get(key) is transfer:
            del self.transfers[key]

    @staticmethod
    def _close_writer(transfer: Transfer) -> None:
        writer, transfer.writer = transfer.writer, None
        _close_quietly(writer)

    @staticmethod
    def _remove_partial(transfer: Transfer) -> None:
        if transfer.save_path and transfer.state != TransferState.COMPLETED:
            try:
                Path(transfer.save_path).unlink(missing_ok=True)
            except OSError as e:
                log.debug(f"[transfer] Could not remove partial {transfer.save_path}: {e}")

    async def _notify(self, transfer: Transfer) -> None:
        if transfer.notified:
            return
        transfer.notified = True
        await self._fire_complete(transfer)

    async def _fire_complete(self, transfer: Transfer) -> None:
        if self.on_complete:
            try:
                await self.on_complete(transfer)
            except Exception as e:
                log.debug(f"[transfer] on_complete failed for {transfer.filename}: {e}")

    def _schedule_notify(self, transfer: Transfer) -> None:
        """Fire on_complete from sync code (abort) without awaiting it here."""
        if transfer.notified:
            return
        transfer.notified = True  # set now so a racing handler doesn't fire it too
        if not self.on_complete:
            return
        task = asyncio.create_task(self._fire_complete(transfer))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    # --- File connections ---

    async def _read_transfer_init(
        self, transfer: Transfer, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> bytes | None:
        """Read the uploader's FileTransferInit (the 4-byte transfer token).
        On failure the connection is closed and None returned."""
        try:
            peer_token = await asyncio.wait_for(reader.readexactly(4), timeout=60)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError) as e:
            log.warning(f"[transfer] No FileTransferInit from {transfer.username}: {e}")
            _close_quietly(writer)
            if transfer.state not in TERMINAL_STATES and not _owned_elsewhere(transfer):
                self.update_state(transfer, TransferState.FAILED, error=f"No response: {e}")
                await self._notify(transfer)
            return None
        log.info(f"[transfer] FileTransferInit from {transfer.username}: {peer_token.hex()}")
        return peer_token

    async def handle_file_transfer_connection(
        self,
        username: str,
        token: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an inbound file transfer connection (PeerInit F or PierceFirewall).

        Protocol (we are the downloader): the uploader sends FileTransferInit
        (the 4-byte transfer token), we send FileOffset (8 bytes), data follows.
        """
        # Provisional pick — try token, then username
        transfer = self.get_transfer_by_token(username, token)
        if not transfer:
            transfer = self.find_transfer_by_token(token)
        if not transfer:
            transfer = self.find_active_transfer_for_user(username)
        if not transfer:
            log.warning(f"[transfer] No transfer found for {username} (token {token.hex()})")
            _close_quietly(writer)
            return

        log.info(f"[transfer] Inbound file transfer from {username}: {transfer.filename}")
        try:
            peer_token = await self._read_transfer_init(transfer, reader, writer)
        except asyncio.CancelledError:
            _close_quietly(writer)
            raise
        if peer_token is None:
            return
        await self._receive(transfer, reader, writer)

    async def handle_outbound_file_transfer(
        self,
        transfer: Transfer,
        host: str,
        port: int,
        token: bytes,
    ) -> None:
        """Connect to peer for file transfer (outbound, server-mediated)."""
        log.info(f"[transfer] Outbound file transfer to {transfer.username} at {host}:{port}")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"[transfer] Outbound connect failed to {transfer.username}: {e}")
            if transfer.state not in TERMINAL_STATES and not _owned_elsewhere(transfer):
                self.update_state(transfer, TransferState.FAILED, error=f"Connect failed: {e}")
                await self._notify(transfer)
            return

        try:
            # Send pierce firewall with the RELAY token (so peer can match the connection)
            writer.write(build_pierce_firewall_raw(token))
            await writer.drain()
            peer_token = await self._read_transfer_init(transfer, reader, writer)
        except asyncio.CancelledError:
            _close_quietly(writer)
            raise
        except (ConnectionError, OSError) as e:
            log.warning(f"[transfer] Outbound handshake failed with {transfer.username}: {e}")
            _close_quietly(writer)
            if transfer.state not in TERMINAL_STATES and not _owned_elsewhere(transfer):
                self.update_state(transfer, TransferState.FAILED, error=f"Handshake failed: {e}")
                await self._notify(transfer)
            return
        if peer_token is None:
            return
        await self._receive(transfer, reader, writer)

    async def _receive(
        self,
        transfer: Transfer,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """The data phase of a file connection, shared by inbound and outbound:
        claim the transfer, send the offset, stream into the staging file and
        settle the final state. Always closes the socket and fires on_complete
        exactly once; being cancelled counts as an abort."""
        if transfer.state in TERMINAL_STATES:
            log.info(f"[transfer] {transfer.filename} is already {transfer.state}; closing connection")
            _close_quietly(writer)
            return

        transfer.task = asyncio.current_task()
        transfer.writer = writer
        short_name = transfer.filename
        try:
            # No resume: always start a fresh file from offset 0.
            transfer.received_bytes = 0
            writer.write(struct.pack("<Q", 0))
            await writer.drain()

            save_path = self.save_path_for(transfer)
            short_name = save_path.name
            save_path.parent.mkdir(parents=True, exist_ok=True)
            transfer.save_path = str(save_path)
            self.update_state(transfer, TransferState.TRANSFERRING)
            log.info(f"[transfer] Downloading from {transfer.username}: {transfer.filename}")

            async with aiofiles.open(save_path, "wb") as f:
                while True:
                    try:
                        chunk = await asyncio.wait_for(reader.read(65536), timeout=60)
                    except asyncio.TimeoutError:
                        if transfer.received_bytes > 0 and (
                            transfer.total_bytes == 0 or
                            transfer.received_bytes >= transfer.total_bytes * 0.95
                        ):
                            break
                        raise ConnectionError("Peer stopped sending data (60s timeout)")
                    if not chunk:
                        break
                    transfer.received_bytes += len(chunk)
                    await f.write(chunk)
                    if self.on_progress:
                        await self.on_progress(transfer)
                    if transfer.total_bytes > 0 and transfer.received_bytes >= transfer.total_bytes:
                        break

            if transfer.received_bytes > 0 and (
                transfer.total_bytes == 0 or
                transfer.received_bytes >= transfer.total_bytes * 0.99
            ):
                self.update_state(transfer, TransferState.COMPLETED)
                log.info(f"[transfer] Completed: {short_name} ({transfer.received_bytes} bytes)")
            elif transfer.received_bytes > 0:
                self.update_state(transfer, TransferState.FAILED,
                                  error=f"Incomplete: {transfer.received_bytes}/{transfer.total_bytes}")
                log.warning(f"[transfer] Incomplete: {short_name} ({transfer.received_bytes}/{transfer.total_bytes})")
            else:
                self.update_state(transfer, TransferState.FAILED, error="No data received")
                log.warning(f"[transfer] No data received for {short_name}")
        except asyncio.CancelledError:
            if transfer.state not in TERMINAL_STATES:
                self.update_state(transfer, TransferState.FAILED, error="Cancelled")
            log.info(f"[transfer] Cancelled: {short_name}")
            raise
        except Exception as e:
            if transfer.state not in TERMINAL_STATES:
                self.update_state(transfer, TransferState.FAILED, error=str(e))
            log.error(f"[transfer] Error downloading {short_name}: {e}")
        finally:
            if transfer.writer is writer:
                transfer.writer = None
            _close_quietly(writer)
            await self._notify(transfer)

    def active_paths(self) -> list[str]:
        """Paths owned by transfers that are still in flight — cleanup must not touch them."""
        paths: list[str] = []
        for t in self.transfers.values():
            if t.state not in ACTIVE_STATES:
                continue
            if t.save_path:
                paths.append(t.save_path)
            folder = self.job_dir(t.job_id) if t.job_id else None
            if folder is not None:
                paths.append(str(folder))
        return paths

    def get_all_transfers(self) -> list[dict]:
        return [t.to_dict() for t in self.transfers.values()]

    def get_active_transfers(self) -> list[dict]:
        return [
            t.to_dict() for t in self.transfers.values()
            if t.state in (TransferState.REQUESTED, TransferState.QUEUED,
                          TransferState.CONNECTED, TransferState.TRANSFERRING)
        ]

    async def _cleanup_loop(self) -> None:
        """Periodically clean up stuck/completed transfers."""
        try:
            while True:
                await asyncio.sleep(60)
                self._sweep(time.time())
        except asyncio.CancelledError:
            return

    def _sweep(self, now: float) -> None:
        """One cleanup pass: expire terminal entries, abort stuck ones."""
        to_remove: list[str] = []
        to_abort: list[tuple[Transfer, str]] = []
        for key, transfer in self.transfers.items():
            age = now - transfer.started_at
            if transfer.state in TERMINAL_STATES:
                if age > 60:  # Keep terminal states for 1 minute
                    to_remove.append(key)
            elif transfer.state in (TransferState.REQUESTED, TransferState.QUEUED):
                if age > 180:  # 3 min for queue timeout (waiting for peer response)
                    log.warning(f"[transfer] Queue timeout: {transfer.filename} ({transfer.state})")
                    to_abort.append((transfer, "Queue timeout"))
            elif transfer.state == TransferState.CONNECTED:
                if age > 120:  # 2 min connected but no data
                    log.warning(f"[transfer] Connected timeout: {transfer.filename}")
                    to_abort.append((transfer, "Connected but no data"))
            elif age > DOWNLOAD_TTL:
                log.warning(f"[transfer] Cleaning up stuck transfer: {transfer.filename}")
                to_abort.append((transfer, "Timed out"))
        for key in to_remove:
            self.transfers.pop(key, None)
        for transfer, error in to_abort:
            self.abort(transfer, error)

    def destroy(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        for t in list(self.transfers.values()):
            if t.task is not None and not t.task.done():
                t.task.cancel()
        self.transfers.clear()


def _owned_elsewhere(transfer: Transfer) -> bool:
    """True when another, still-running task is handling this transfer's file connection."""
    task = transfer.task
    if task is None or task.done():
        return False
    try:
        return task is not asyncio.current_task()
    except RuntimeError:
        return True


def _close_quietly(writer: asyncio.StreamWriter | None) -> None:
    if writer is None:
        return
    try:
        writer.close()
    except Exception:
        pass
