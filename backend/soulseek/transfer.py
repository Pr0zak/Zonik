"""Download transfer state machine and file I/O."""
from __future__ import annotations

import asyncio
import logging
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


@dataclass
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
        }


class TransferManager:
    """Manages active file transfers."""

    def __init__(
        self,
        download_dir: str = "/downloads",
        on_progress: Callable[[Transfer], Awaitable[None]] | None = None,
        on_complete: Callable[[Transfer], Awaitable[None]] | None = None,
    ):
        self.download_dir = download_dir
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.transfers: dict[str, Transfer] = {}  # keyed by "username:filename"
        self._cleanup_task: asyncio.Task | None = None

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

    def create_transfer(self, username: str, filename: str) -> Transfer:
        key = self._normalize_key(username, filename)
        transfer = Transfer(username=username, filename=filename)
        self.transfers[key] = transfer
        return transfer

    def remove_transfer(self, username: str, filename: str) -> None:
        self.transfers.pop(self._normalize_key(username, filename), None)

    def update_state(self, transfer: Transfer, state: str, **kwargs) -> None:
        transfer.state = state
        for k, v in kwargs.items():
            setattr(transfer, k, v)

    async def handle_file_transfer_connection(
        self,
        username: str,
        token: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an inbound file transfer connection.

        Protocol (we are the downloader):
        1. Connection established (pierce_firewall already parsed)
        2. We SEND transfer_token (4 bytes) — tells peer which file
        3. We SEND file_offset (8 bytes) — resume position
        4. Peer sends file data
        """
        # Find the transfer — try token, then username
        transfer = self.get_transfer_by_token(username, token)
        if not transfer:
            transfer = self.find_transfer_by_token(token)
        if not transfer:
            transfer = self.find_active_transfer_for_user(username)
        if not transfer:
            log.warning(f"[transfer] No transfer found for {username} (token {token.hex()})")
            writer.close()
            return

        log.info(f"[transfer] Starting file transfer from {username}: {transfer.filename}")
        self.update_state(transfer, TransferState.TRANSFERRING)

        # Send transfer token (4 bytes) — tells peer which file we want
        if transfer.token:
            writer.write(transfer.token)
        else:
            writer.write(token)

        # Send file offset (resume position)
        writer.write(struct.pack("<Q", transfer.received_bytes))
        await writer.drain()

        # Determine save path
        short_name = transfer.filename.rsplit("\\", 1)[-1]
        save_path = Path(self.download_dir) / short_name
        save_path.parent.mkdir(parents=True, exist_ok=True)
        transfer.save_path = str(save_path)

        try:
            async with aiofiles.open(save_path, "wb") as f:
                while True:
                    try:
                        chunk = await asyncio.wait_for(reader.read(65536), timeout=30)
                    except asyncio.TimeoutError:
                        raise ConnectionError("Peer stopped sending data (30s timeout)")
                    if not chunk:
                        break

                    transfer.received_bytes += len(chunk)
                    await f.write(chunk)

                    if self.on_progress:
                        await self.on_progress(transfer)

                    if transfer.total_bytes > 0 and transfer.received_bytes >= transfer.total_bytes:
                        break

            if transfer.total_bytes > 0 and transfer.received_bytes >= transfer.total_bytes:
                self.update_state(transfer, TransferState.COMPLETED)
                log.info(f"[transfer] Completed: {short_name} ({transfer.received_bytes} bytes)")
            else:
                self.update_state(transfer, TransferState.FAILED, error="Connection closed before complete")
                log.warning(f"[transfer] Incomplete: {short_name} ({transfer.received_bytes}/{transfer.total_bytes})")
        except Exception as e:
            self.update_state(transfer, TransferState.FAILED, error=str(e))
            log.error(f"[transfer] Error downloading {short_name}: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass
            if self.on_complete:
                await self.on_complete(transfer)

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
        except Exception as e:
            log.warning(f"[transfer] Outbound connect failed to {transfer.username}: {e}")
            self.update_state(transfer, TransferState.FAILED, error=f"Connect failed: {e}")
            return

        # Send pierce firewall with the RELAY token (so peer can match the connection)
        pf_msg = build_pierce_firewall_raw(token)
        writer.write(pf_msg)
        await writer.drain()

        # Send transfer token (identifies which file) + file offset (resume position)
        xfer_token = transfer.token or token
        offset_bytes = struct.pack("<Q", transfer.received_bytes)
        log.info(f"[transfer] Handshake: relay={token.hex()}, xfer={xfer_token.hex()}, offset={transfer.received_bytes}")
        writer.write(xfer_token)
        writer.write(offset_bytes)
        await writer.drain()

        log.info(f"[transfer] Starting file transfer from {transfer.username}: {transfer.filename}")
        self.update_state(transfer, TransferState.TRANSFERRING)

        # Determine save path
        short_name = transfer.filename.rsplit("\\", 1)[-1]
        save_path = Path(self.download_dir) / short_name
        save_path.parent.mkdir(parents=True, exist_ok=True)
        transfer.save_path = str(save_path)

        try:
            async with aiofiles.open(save_path, "wb") as f:
                while True:
                    try:
                        chunk = await asyncio.wait_for(reader.read(65536), timeout=30)
                    except asyncio.TimeoutError:
                        raise ConnectionError("Peer stopped sending data (30s timeout)")
                    if not chunk:
                        break
                    transfer.received_bytes += len(chunk)
                    await f.write(chunk)
                    if self.on_progress:
                        await self.on_progress(transfer)
                    if transfer.total_bytes > 0 and transfer.received_bytes >= transfer.total_bytes:
                        break

            if transfer.total_bytes > 0 and transfer.received_bytes >= transfer.total_bytes:
                self.update_state(transfer, TransferState.COMPLETED)
                log.info(f"[transfer] Completed: {short_name} ({transfer.received_bytes} bytes)")
            else:
                self.update_state(transfer, TransferState.FAILED, error="Connection closed before complete")
                log.warning(f"[transfer] Incomplete: {short_name} ({transfer.received_bytes}/{transfer.total_bytes})")
        except Exception as e:
            self.update_state(transfer, TransferState.FAILED, error=str(e))
            log.error(f"[transfer] Error downloading {short_name}: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass
            if self.on_complete:
                await self.on_complete(transfer)

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
                now = time.time()
                to_remove = []
                for key, transfer in self.transfers.items():
                    age = now - transfer.started_at
                    if transfer.state in (TransferState.COMPLETED, TransferState.FAILED, TransferState.DENIED):
                        if age > 60:  # Keep terminal states for 1 minute
                            to_remove.append(key)
                    elif transfer.state in (TransferState.REQUESTED, TransferState.QUEUED):
                        if age > 180:  # 3 min for queue timeout (waiting for peer response)
                            log.warning(f"[transfer] Queue timeout: {transfer.filename} ({transfer.state})")
                            transfer.state = TransferState.FAILED
                            transfer.error = "Queue timeout"
                            to_remove.append(key)
                    elif transfer.state == TransferState.CONNECTED:
                        if age > 120:  # 2 min connected but no data
                            log.warning(f"[transfer] Connected timeout: {transfer.filename}")
                            transfer.state = TransferState.FAILED
                            transfer.error = "Connected but no data"
                            to_remove.append(key)
                    elif age > DOWNLOAD_TTL:
                        log.warning(f"[transfer] Cleaning up stuck transfer: {transfer.filename}")
                        to_remove.append(key)
                for key in to_remove:
                    del self.transfers[key]
        except asyncio.CancelledError:
            return

    def destroy(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        self.transfers.clear()
