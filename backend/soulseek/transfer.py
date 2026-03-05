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

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "filename": self.filename,
            "state": self.state,
            "total_bytes": self.total_bytes,
            "received_bytes": self.received_bytes,
            "progress": round(self.progress * 100, 1),
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

    def get_transfer(self, username: str, filename: str) -> Transfer | None:
        return self.transfers.get(f"{username}:{filename}")

    def get_transfer_by_token(self, username: str, token: bytes) -> Transfer | None:
        for t in self.transfers.values():
            if t.username == username and t.token == token:
                return t
        return None

    def create_transfer(self, username: str, filename: str) -> Transfer:
        key = f"{username}:{filename}"
        transfer = Transfer(username=username, filename=filename)
        self.transfers[key] = transfer
        return transfer

    def remove_transfer(self, username: str, filename: str) -> None:
        self.transfers.pop(f"{username}:{filename}", None)

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

        Protocol: peer sends token (4 bytes), we match to transfer, send file offset (8 bytes),
        then receive file data until complete.
        """
        transfer = self.get_transfer_by_token(username, token)
        if not transfer:
            log.warning(f"[transfer] No transfer found for token from {username}")
            writer.close()
            return

        self.update_state(transfer, TransferState.TRANSFERRING)

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
                    chunk = await reader.read(65536)
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
                if self.on_complete:
                    await self.on_complete(transfer)
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

    async def handle_outbound_file_transfer(
        self,
        transfer: Transfer,
        host: str,
        port: int,
        token: bytes,
    ) -> None:
        """Connect to peer for file transfer (outbound, server-mediated)."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10
            )
        except Exception as e:
            self.update_state(transfer, TransferState.FAILED, error=f"Connect failed: {e}")
            return

        # Send pierce firewall
        writer.write(build_pierce_firewall_raw(token))
        await writer.drain()

        # Read the token echo (4 bytes) from peer
        try:
            echo_data = await asyncio.wait_for(reader.readexactly(4), timeout=10)
        except Exception:
            self.update_state(transfer, TransferState.FAILED, error="No token echo")
            writer.close()
            return

        # Now handle the transfer like an inbound one
        await self.handle_file_transfer_connection(
            transfer.username, token, reader, writer
        )

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
                        if age > 60:  # Keep completed/failed for 1 minute
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
