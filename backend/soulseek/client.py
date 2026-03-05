"""SoulseekClient — orchestrates server, peers, listener, and transfers."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from backend.soulseek.server_conn import ServerConnection
from backend.soulseek.listener import PeerListener
from backend.soulseek.peer import PeerConnection
from backend.soulseek.transfer import TransferManager, Transfer
from backend.soulseek.reputation import PeerReputation
from backend.soulseek.protocol.types import (
    ConnectionType, TransferDirection, TransferState, SearchResult, FileInfo,
)

log = logging.getLogger(__name__)

DEFAULT_SEARCH_TIMEOUT = 25
DEFAULT_PEER_TIMEOUT = 20


class SoulseekClient:
    """High-level Soulseek client — search, download, peer management."""

    def __init__(
        self,
        server_host: str = "server.slsknet.org",
        server_port: int = 2242,
        listen_port: int = 2234,
        download_dir: str | None = None,
    ):
        if download_dir is None:
            from backend.config import get_settings
            download_dir = get_settings().soulseek.download_dir

        self.server = ServerConnection(
            host=server_host,
            port=server_port,
            listen_port=listen_port,
            on_message=self._handle_server_message,
            on_disconnect=self._handle_server_disconnect,
        )
        self.listener = PeerListener(
            port=listen_port,
            on_connection=self._handle_inbound_connection,
        )
        self.transfers = TransferManager(
            download_dir=download_dir,
            on_progress=self._on_transfer_progress,
            on_complete=self._on_transfer_complete,
        )
        self.reputation = PeerReputation()

        self.peers: dict[str, PeerConnection] = {}
        self._search_results: dict[bytes, list[SearchResult]] = {}
        self._search_events: dict[bytes, asyncio.Event] = {}
        self._peer_address_futures: dict[str, asyncio.Future] = {}
        self._last_broadcast: float = 0
        self._peer_cleanup_task: asyncio.Task | None = None

    @property
    def logged_in(self) -> bool:
        return self.server.logged_in

    @property
    def username(self) -> str | None:
        return self.server.username

    async def connect_and_login(self, username: str, password: str) -> None:
        """Connect to server, start listener, login."""
        await self.listener.start()
        self.transfers.start()
        self._peer_cleanup_task = asyncio.create_task(self._peer_cleanup_loop())
        await self.server.connect_and_login(username, password)

    async def search(
        self,
        query: str,
        timeout: float = DEFAULT_SEARCH_TIMEOUT,
        max_responses: int = 50,
    ) -> list[SearchResult]:
        """Search the Soulseek network and collect results for `timeout` seconds."""
        token = os.urandom(4)
        self._search_results[token] = []
        self._search_events[token] = asyncio.Event()

        await self.server.file_search(token, query)

        # Wait for timeout or max_responses
        try:
            await asyncio.wait_for(self._search_events[token].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        results = self._search_results.pop(token, [])
        self._search_events.pop(token, None)
        return results[:max_responses]

    async def download(self, username: str, filename: str) -> Transfer:
        """Initiate a download from a specific user."""
        peer = await self._get_or_connect_peer(username)

        transfer = self.transfers.create_transfer(username, filename)
        await peer.send_queue_upload(filename)
        await peer.send_place_in_queue_request(filename)

        return transfer

    async def _get_or_connect_peer(self, username: str, timeout: float = DEFAULT_PEER_TIMEOUT) -> PeerConnection:
        """Get existing peer or establish new connection (races direct vs indirect)."""
        existing = self.peers.get(username)
        if existing:
            return existing

        token = os.urandom(4)

        async def try_direct() -> PeerConnection:
            """Connect directly to peer via IP from server."""
            addr = await self._request_peer_address(username, timeout=timeout)
            peer = await PeerConnection.connect_direct(
                addr["host"], addr["port"], username,
                on_message=self._handle_peer_message,
                on_close=self._handle_peer_close,
                timeout=timeout,
            )
            await peer.send_peer_init(self.server.username, ConnectionType.PEER_TO_PEER, token)
            peer.start_reading()
            return peer

        async def try_indirect() -> PeerConnection:
            """Ask server to tell peer to connect to us."""
            future: asyncio.Future[PeerConnection] = asyncio.get_event_loop().create_future()

            original_handler = self.listener.on_connection

            async def listen_handler(msg, reader, writer):
                if msg.get("kind") == "pierce_firewall" and msg.get("token") == token:
                    peer = PeerConnection(
                        reader, writer, username,
                        on_message=self._handle_peer_message,
                        on_close=self._handle_peer_close,
                    )
                    peer.start_reading()
                    if not future.done():
                        future.set_result(peer)
                elif original_handler:
                    await original_handler(msg, reader, writer)

            self.listener.on_connection = listen_handler
            await self.server.connect_to_peer(token, username, ConnectionType.PEER_TO_PEER)

            try:
                return await asyncio.wait_for(future, timeout=timeout)
            finally:
                self.listener.on_connection = original_handler

        # Race both approaches
        direct_task = asyncio.create_task(try_direct())
        indirect_task = asyncio.create_task(try_indirect())

        done, pending = await asyncio.wait(
            {direct_task, indirect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel losers
        for task in pending:
            task.cancel()

        peer = None
        errors = []
        for task in done:
            try:
                peer = task.result()
                break
            except Exception as e:
                errors.append(e)

        if peer is None:
            # Also check if any pending tasks completed
            for task in pending:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            raise ConnectionError(f"Cannot connect to {username}: {errors}")

        # Clean up losing peer
        for task in pending:
            try:
                result = task.result() if task.done() else None
                if result and result != peer:
                    result.destroy()
            except Exception:
                pass

        self.peers[username] = peer
        return peer

    async def _request_peer_address(self, username: str, timeout: float = 10) -> dict:
        """Request peer address from server and wait for response."""
        future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._peer_address_futures[username] = future
        await self.server.get_peer_address(username)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._peer_address_futures.pop(username, None)

    # --- Server message handlers ---

    async def _handle_server_message(self, msg: dict) -> None:
        kind = msg.get("kind")

        if kind == "get_peer_address":
            future = self._peer_address_futures.get(msg["username"])
            if future and not future.done():
                future.set_result({"host": msg["host"], "port": msg["port"]})

        elif kind == "connect_to_peer":
            conn_type = msg.get("type")
            username = msg["username"]
            token = msg["token"]
            host = msg["host"]
            port = msg["port"]

            if conn_type == ConnectionType.PEER_TO_PEER:
                if username not in self.peers:
                    asyncio.create_task(self._accept_indirect_peer(username, host, port, token))

            elif conn_type == ConnectionType.FILE_TRANSFER:
                transfer = self.transfers.get_transfer_by_token(username, token)
                if transfer:
                    asyncio.create_task(
                        self.transfers.handle_outbound_file_transfer(transfer, host, port, token)
                    )

        elif kind == "possible_parents":
            pass  # We don't participate in distributed network

    async def _accept_indirect_peer(self, username: str, host: str, port: int, token: bytes) -> None:
        """Handle server-mediated peer connection (we connect to them)."""
        try:
            peer = await PeerConnection.connect_direct(
                host, port, username,
                on_message=self._handle_peer_message,
                on_close=self._handle_peer_close,
            )
            await peer.send_pierce_firewall(token)
            peer.start_reading()
            self.peers[username] = peer
        except Exception as e:
            log.debug(f"[client] Failed to connect to indirect peer {username}: {e}")
            await self.server.cant_connect_to_peer(token, username)

    async def _handle_server_disconnect(self) -> None:
        log.warning("[client] Server disconnected")

    # --- Peer message handlers ---

    async def _handle_peer_message(self, msg: dict, peer: PeerConnection) -> None:
        kind = msg.get("kind")

        if kind == "file_search_response":
            token = msg["token"]
            if token in self._search_results:
                result = SearchResult(
                    username=msg["username"],
                    token=token.hex(),
                    files=msg["files"],
                    slots_free=msg["slots_free"],
                    avg_speed=msg["avg_speed"],
                    queue_length=msg["queue_length"],
                )
                self._search_results[token].append(result)

        elif kind == "transfer_request":
            if msg.get("direction") == TransferDirection.UPLOAD:
                transfer = self.transfers.get_transfer(peer.username, msg["filename"])
                if transfer:
                    transfer.token = msg["token"]
                    transfer.total_bytes = msg.get("size", 0)
                    self.transfers.update_state(transfer, TransferState.CONNECTED)
                    await peer.send_transfer_response(msg["token"], True)
                else:
                    log.warning(f"[client] No transfer for upload request: {msg['filename']}")

        elif kind == "place_in_queue_response":
            transfer = self.transfers.get_transfer(peer.username, msg["filename"])
            if transfer:
                if transfer.state == TransferState.REQUESTED:
                    self.transfers.update_state(transfer, TransferState.QUEUED)
                # Update queue position info (could add to Transfer dataclass)

        elif kind == "upload_denied":
            transfer = self.transfers.get_transfer(peer.username, msg["filename"])
            if transfer:
                self.transfers.update_state(transfer, TransferState.DENIED, error=msg.get("reason", ""))
                await self._on_transfer_complete(transfer)

        elif kind == "upload_failed":
            transfer = self.transfers.get_transfer(peer.username, msg["filename"])
            if transfer:
                self.transfers.update_state(transfer, TransferState.FAILED, error="Upload failed by peer")
                await self._on_transfer_complete(transfer)

    async def _handle_peer_close(self, peer: PeerConnection) -> None:
        self.peers.pop(peer.username, None)

    # --- Inbound connection handlers ---

    async def _handle_inbound_connection(
        self, msg: dict, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        kind = msg.get("kind")

        if kind == "peer_init":
            username = msg["username"]
            if username in self.peers:
                writer.close()
                return

            peer = PeerConnection(
                reader, writer, username,
                on_message=self._handle_peer_message,
                on_close=self._handle_peer_close,
            )
            peer.start_reading()
            self.peers[username] = peer

        elif kind == "pierce_firewall":
            # This is handled by the _get_or_connect_peer listener override
            # or by the transfer connection handler
            pass

    # --- Transfer callbacks ---

    async def _on_transfer_progress(self, transfer: Transfer) -> None:
        """Called during file download for progress updates (throttled to 500ms)."""
        now = time.monotonic()
        if now - self._last_broadcast < 0.5:
            return
        self._last_broadcast = now
        await self._broadcast_transfers()

    async def _on_transfer_complete(self, transfer: Transfer) -> None:
        """Called when download completes or fails."""
        if transfer.state == TransferState.COMPLETED:
            await self.reputation.record_success(transfer.username)
        else:
            await self.reputation.record_failure(transfer.username)
        await self._broadcast_transfers()
        # Don't remove immediately — let poll_transfer see the final state.
        # The cleanup loop will remove terminal transfers after 60s.

    async def _broadcast_transfers(self) -> None:
        """Broadcast current transfers to all WebSocket clients."""
        try:
            from backend.api.websocket import broadcast_transfer_progress
            await broadcast_transfer_progress(self.transfers.get_all_transfers())
        except Exception:
            pass

    async def _peer_cleanup_loop(self) -> None:
        """Close idle peer connections to prevent fd leaks."""
        try:
            while True:
                await asyncio.sleep(120)
                # Find peers with no active transfers
                active_users = {t.username for t in self.transfers.transfers.values()}
                idle = [u for u in list(self.peers) if u not in active_users]
                for username in idle:
                    peer = self.peers.pop(username, None)
                    if peer:
                        peer.destroy()
                if idle:
                    log.debug(f"[client] Cleaned up {len(idle)} idle peer connections")
        except asyncio.CancelledError:
            return

    def destroy(self) -> None:
        """Tear down all connections."""
        if self._peer_cleanup_task and not self._peer_cleanup_task.done():
            self._peer_cleanup_task.cancel()
        self.server.destroy()
        self.listener.destroy()
        self.transfers.destroy()
        for peer in list(self.peers.values()):
            peer.destroy()
        self.peers.clear()
        self._search_results.clear()
        self._search_events.clear()
        self._peer_address_futures.clear()
