"""SoulseekClient — orchestrates server, peers, listener, and transfers."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time

from backend.soulseek.server_conn import ServerConnection
from backend.soulseek.listener import PeerListener
from backend.soulseek.peer import PeerConnection
from backend.soulseek.transfer import TransferManager, Transfer, TERMINAL_STATES
from backend.soulseek.upload import UploadManager
from backend.soulseek.reputation import PeerReputation
from backend.soulseek.protocol.peer_messages import build_peer_init, build_place_in_queue_response
from backend.soulseek.protocol.types import (
    ConnectionType, TransferDirection, TransferState, SearchResult, FileInfo,
)

log = logging.getLogger(__name__)

DEFAULT_SEARCH_TIMEOUT = 25
SEARCH_MIN_WAIT = 5.0   # never return before this, so slower peers get a chance
SEARCH_QUIET = 3.0      # ...then stop once no new response for this long
DEFAULT_PEER_TIMEOUT = 20
SHARE_REFRESH_SECONDS = 6 * 3600  # rebuild the shared list from the library this often
SHARE_RETRY_SECONDS = 300         # ...or this soon while it is still empty
SHARING_CHECK_SECONDS = 30        # how long a read of share_library is reused


class PeerBusy(Exception):
    """Another download holds this peer's one-file-at-a-time slot."""


class SoulseekClient:
    """High-level Soulseek client — search, download, peer management."""

    def __init__(
        self,
        server_host: str = "server.slsknet.org",
        server_port: int = 2242,
        listen_port: int = 2234,
        staging_dir: str | None = None,
    ):
        from backend.config import get_settings
        slsk_cfg = get_settings().soulseek
        if staging_dir is None:
            staging_dir = slsk_cfg.staging_dir
        max_transfer_seconds = max(1, slsk_cfg.transfer_max_minutes) * 60

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
            staging_dir=staging_dir,
            max_transfer_seconds=max_transfer_seconds,
            on_progress=self._on_transfer_progress,
            on_complete=self._on_transfer_complete,
        )
        self.reputation = PeerReputation()
        self.uploads = UploadManager(
            get_peer=self._get_or_connect_peer,
            open_file_connection=self._open_upload_connection,
            enabled=self._sharing_enabled,
            slots=slsk_cfg.upload_slots,
            speed_limit_kbps=slsk_cfg.upload_speed_limit_kbps,
            on_change=self._on_upload_change,
            send_if_connected=self._send_if_connected,
        )
        self.transfers.uploads = self.uploads  # get_all_uploads(); never mixed into downloads
        self._sharing = (slsk_cfg.share_library, time.monotonic())
        # Relay tokens of our upload F connections the server was asked to set up:
        # the peer answers with a PierceFirewall carrying that token.
        self._upload_relays: dict[bytes, asyncio.Future] = {}
        self._share_task: asyncio.Task | None = None
        # Set when share_library flips, so the refresh loop rebuilds (or clears)
        # the list and re-reports the counts now instead of at its next interval.
        self._share_wake = asyncio.Event()

        self.peers: dict[str, PeerConnection] = {}
        self._search_results: dict[bytes, list[SearchResult]] = {}
        self._search_events: dict[bytes, asyncio.Event] = {}
        self._search_max: dict[bytes, int] = {}
        self._search_last: dict[bytes, float] = {}
        # Every caller waiting on one user's address gets the answer (an upload's
        # direct connect and a download's peer connect can ask at the same time).
        self._peer_address_futures: dict[str, list[asyncio.Future]] = {}
        self._last_broadcast: float = 0
        self._peer_cleanup_task: asyncio.Task | None = None
        self._file_tasks: set[asyncio.Task] = set()
        # Per-peer lock: [semaphore, holders+waiters]; entries are pruned when idle.
        self._peer_slots: dict[str, list] = {}

    @property
    def logged_in(self) -> bool:
        return self.server.logged_in

    @property
    def username(self) -> str | None:
        return self.server.username

    async def connect_and_login(self, username: str, password: str) -> None:
        """Connect to server, start listener, login."""
        try:
            await self.listener.start()
            self.transfers.start()
            self.uploads.start()
            self._peer_cleanup_task = asyncio.create_task(self._peer_cleanup_loop())
            # Log in with whatever counts are cached (1/1 when none yet); the shared
            # list is built in the background and the real counts reported once it
            # is ready. Startup never waits for it.
            await self.server.connect_and_login(username, password)
        except BaseException:
            self.destroy()  # don't leave the listener and background loops running
            raise
        self._share_task = asyncio.create_task(self._share_refresh_loop())

    async def refresh_shares(self) -> tuple[int, int]:
        """Rebuild the shared list (from the track table; a filesystem walk in a
        thread only when the table is empty) and report the counts to the server."""
        from backend.config import get_settings
        from backend.soulseek.shares import refresh_shares_async
        settings = get_settings()
        self._sharing = (settings.soulseek.share_library, time.monotonic())
        num_dirs, num_files = await refresh_shares_async(
            settings.library.music_dir,
            share_library=settings.soulseek.share_library,
        )
        log.info(f"[client] Shares refreshed: {num_files} files in {num_dirs} dirs")
        if self.server.logged_in:
            await self._report_shares_to_server()
        return num_dirs, num_files

    async def _share_refresh_loop(self) -> None:
        """Build the shared list now, then every SHARE_REFRESH_SECONDS (sooner
        while it is still empty but sharing is on)."""
        try:
            while True:
                delay = SHARE_REFRESH_SECONDS
                try:
                    _, num_files = await self.refresh_shares()
                    if num_files == 0 and self._sharing_enabled():
                        delay = SHARE_RETRY_SECONDS
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning(f"[client] Share refresh failed: {e}")
                    delay = SHARE_RETRY_SECONDS
                self._share_wake.clear()
                try:
                    await asyncio.wait_for(self._share_wake.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            return

    def _sharing_enabled(self) -> bool:
        """settings.soulseek.share_library, re-read at most every SHARING_CHECK_SECONDS
        (get_settings() parses zonik.toml on every call)."""
        value, at = self._sharing
        now = time.monotonic()
        if now - at > SHARING_CHECK_SECONDS:
            try:
                from backend.config import get_settings
                value = get_settings().soulseek.share_library
            except Exception:
                pass
            if value != self._sharing[0]:
                log.info(f"[client] share_library is now {value}; refreshing shares")
                self._share_wake.set()
            self._sharing = (value, now)
        return value

    def _send_if_connected(self, username: str, data: bytes) -> bool:
        """Write a pre-built message on an open P connection without awaiting it
        (for notices sent while shutting down). False if there is no connection."""
        peer = self.peers.get(username)
        if peer is None:
            return False
        try:
            peer._stream.writer.write(data)
        except Exception:
            return False
        return True

    async def _report_shares_to_server(self) -> None:
        """Report current share counts to the Soulseek server."""
        from backend.soulseek.shares import get_share_counts
        from backend.soulseek.protocol.server_messages import build_shared_folders_files
        num_dirs, num_files = get_share_counts()
        if num_dirs == 0:
            num_dirs, num_files = 1, 1
        await self.server._send(build_shared_folders_files(num_dirs, num_files))
        log.info(f"[client] Reported shares to server: {num_files} files in {num_dirs} dirs")

    async def search(
        self,
        query: str,
        timeout: float = DEFAULT_SEARCH_TIMEOUT,
        max_responses: int = 50,
    ) -> list[SearchResult]:
        """Search the Soulseek network and collect results.

        Returns as soon as results settle — at least SEARCH_MIN_WAIT seconds in,
        with responses in hand and none new for SEARCH_QUIET seconds — or when
        max_responses peers have answered. Only a search nobody answers waits
        the full `timeout`.
        """
        token = os.urandom(4)
        results_list: list[SearchResult] = []
        event = asyncio.Event()
        self._search_results[token] = results_list
        self._search_events[token] = event
        self._search_max[token] = max_responses
        loop = asyncio.get_running_loop()
        started = loop.time()
        self._search_last[token] = started

        try:
            await self.server.file_search(token, query)
            while True:
                now = loop.time()
                remaining = timeout - (now - started)
                if remaining <= 0 or event.is_set():
                    break
                if (
                    results_list
                    and now - started >= SEARCH_MIN_WAIT
                    and now - self._search_last.get(token, started) >= SEARCH_QUIET
                ):
                    break
                try:
                    await asyncio.wait_for(event.wait(), timeout=min(0.5, remaining))
                except asyncio.TimeoutError:
                    pass
        finally:
            self._search_results.pop(token, None)
            self._search_events.pop(token, None)
            self._search_max.pop(token, None)
            self._search_last.pop(token, None)
        return results_list[:max_responses]

    async def download(self, username: str, filename: str, job_id: str | None = None) -> Transfer:
        """Initiate a download from a specific user. job_id links the transfer to its Job for progress sync."""
        peer = await self._get_or_connect_peer(username)

        transfer = self.transfers.create_transfer(username, filename, job_id=job_id)
        try:
            await peer.send_queue_upload(filename)
            await peer.send_place_in_queue_request(filename)
        except BaseException:
            # Never queued — don't leave a REQUESTED entry behind to time out later.
            self.transfers.remove_transfer(username, filename)
            raise

        return transfer

    @contextlib.asynccontextmanager
    async def peer_slot(self, username: str, timeout: float | None = None):
        """Hold the one-file-at-a-time slot for a peer around queueing and
        transferring one file. Peers serve one upload at a time, so a second file
        queued to the same peer just waits on their side while holding one of our
        transfer slots.

        With a timeout, raises PeerBusy if the slot isn't free in time, so the
        caller can try another source instead of waiting out someone else's
        transfer."""
        entry = self._peer_slots.get(username)
        if entry is None:
            entry = [asyncio.Semaphore(1), 0]
            self._peer_slots[username] = entry
        entry[1] += 1
        try:
            if timeout is None:
                await entry[0].acquire()
            else:
                try:
                    await asyncio.wait_for(entry[0].acquire(), timeout)
                except asyncio.TimeoutError:
                    raise PeerBusy(username) from None
            try:
                yield
            finally:
                entry[0].release()
        finally:
            entry[1] -= 1
            if entry[1] == 0 and self._peer_slots.get(username) is entry:
                del self._peer_slots[username]

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
        future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        waiting = self._peer_address_futures.setdefault(username, [])
        waiting.append(future)
        try:
            await self.server.get_peer_address(username)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            if future in waiting:
                waiting.remove(future)
            if not waiting and self._peer_address_futures.get(username) is waiting:
                del self._peer_address_futures[username]

    # --- Server message handlers ---

    async def _handle_server_message(self, msg: dict) -> None:
        kind = msg.get("kind")

        if kind == "get_peer_address":
            for future in list(self._peer_address_futures.get(msg["username"], ())):
                if not future.done():
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
                # The relay token differs from the transfer token, so this is only a
                # provisional pick (by username as a last resort); the handler
                # re-resolves it from the uploader's FileTransferInit token.
                # Every lookup is scoped to this user: a token-only match could be
                # another user's transfer that happens to share the token value.
                by_token = True
                transfer = self.transfers.get_transfer_by_token(username, token)
                if not transfer:
                    by_token = False
                    transfer = self.transfers.find_active_transfer_for_user(username)
                if transfer:
                    log.info(f"[client] Server-mediated file transfer to {username} at {host}:{port}")
                    # token = relay token (for pierce_firewall), transfer.token = file token (for handshake)
                    self._start_file_task(
                        transfer if by_token else None,
                        self.transfers.handle_outbound_file_transfer(
                            transfer, host, port, token, matched_by_token=by_token,
                        ),
                    )
                else:
                    log.warning(f"[client] connect_to_peer FILE_TRANSFER but no matching transfer for {username}")

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

        if kind == "shared_file_list_request":
            from backend.soulseek.shares import get_shared_file_list_response
            response = get_shared_file_list_response()
            if response:
                try:
                    await peer.send_raw(response)
                    log.info(f"[client] Sent shared file list to {peer.username}")
                except Exception as e:
                    log.warning(f"[client] Failed to send share list to {peer.username}: {e}")
            return

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
                self._search_last[token] = asyncio.get_running_loop().time()
                if len(self._search_results[token]) >= self._search_max.get(token, 50):
                    event = self._search_events.get(token)
                    if event:
                        event.set()

        elif kind == "transfer_request":
            if msg.get("direction") == TransferDirection.UPLOAD:
                transfer = self.transfers.get_transfer(peer.username, msg["filename"])
                if transfer and transfer.state in TERMINAL_STATES:
                    transfer = None  # we gave up on it — don't revive an abandoned transfer
                if transfer and (transfer.state == TransferState.TRANSFERRING or transfer.receiving):
                    # Already streaming on a live connection: resetting its token and
                    # size here would let a second connection take it over.
                    await peer.send_transfer_response(msg["token"], False, "Transfer already in progress")
                    log.warning(f"[client] Refused repeat transfer request from {peer.username}: "
                                f"{msg['filename']} is already transferring")
                    return
                if transfer:
                    transfer.token = msg["token"]
                    transfer.total_bytes = msg.get("size", 0)
                    self.transfers.update_state(transfer, TransferState.CONNECTED)
                    await peer.send_transfer_response(msg["token"], True)
                    log.info(f"[client] Accepted transfer from {peer.username}: {msg['filename']} ({msg.get('size', 0)} bytes)")
                else:
                    await peer.send_transfer_response(msg["token"], False, "File not queued")
                    active = [f"{t.filename}" for t in self.transfers.transfers.values() if t.username == peer.username]
                    log.warning(f"[client] Rejected transfer request from {peer.username}: {msg['filename']} (active: {active or 'none'})")
            elif msg.get("direction") == TransferDirection.DOWNLOAD:
                # Older clients ask for a file this way instead of QueueUpload: queue
                # it and say "Queued"; our own TransferRequest follows when a slot frees.
                reason = self.uploads.queue(peer.username, msg["filename"])
                await peer.send_transfer_response(msg["token"], False, reason or "Queued")

        elif kind == "place_in_queue_response":
            transfer = self.transfers.get_transfer(peer.username, msg["filename"])
            if transfer:
                if transfer.state == TransferState.REQUESTED:
                    self.transfers.update_state(transfer, TransferState.QUEUED)
                # Update queue position info (could add to Transfer dataclass)

        elif kind == "upload_denied":
            transfer = self.transfers.get_transfer(peer.username, msg["filename"])
            if transfer and transfer.state not in TERMINAL_STATES:
                reason = msg.get("reason", "")
                log.warning(f"[client] Upload denied by {peer.username}: {reason}")
                self.transfers.update_state(transfer, TransferState.DENIED, error=reason)
                self.transfers.abort(transfer, reason)  # fires on_complete once

        elif kind == "place_in_queue_request":
            place = self.uploads.place_in_queue(peer.username, msg["filename"])
            if place is not None:
                await peer.send_raw(build_place_in_queue_response(msg["filename"], place))

        elif kind == "transfer_response":
            # The answer to one of our upload TransferRequests (matched by user + token).
            if self.uploads.handle_transfer_response(
                peer.username, msg["token"], bool(msg.get("allowed")), msg.get("reason", ""),
            ):
                return
            # Peer rejected our transfer request
            if not msg.get("allowed"):
                transfer = self.transfers.get_transfer_by_token(peer.username, msg["token"])
                if transfer and transfer.state not in TERMINAL_STATES:
                    reason = msg.get("reason", "Rejected by peer")
                    self.transfers.update_state(transfer, TransferState.DENIED, error=reason)
                    self.transfers.abort(transfer, reason)

        elif kind == "upload_failed":
            transfer = self.transfers.get_transfer(peer.username, msg["filename"])
            if transfer and transfer.state not in TERMINAL_STATES:
                log.warning(f"[client] Upload failed by {peer.username}: {msg.get('filename', '?')}")
                # Stops the handler if it is still receiving, deletes the partial, notifies once.
                self.transfers.abort(transfer, "Upload failed by peer")

        elif kind == "queue_upload":
            # Peer wants to download from us: queue it if it is in our shares
            # (and sharing is on), else deny.
            reason = self.uploads.queue(peer.username, msg["filename"])
            if reason:
                log.info(f"[client] Queue upload request from {peer.username}: {msg['filename']} (denied: {reason})")
                await peer.send_upload_denied(msg["filename"], reason)

    async def _handle_peer_close(self, peer: PeerConnection) -> None:
        self.peers.pop(peer.username, None)

    # --- Inbound connection handlers ---

    async def _handle_inbound_connection(
        self, msg: dict, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        kind = msg.get("kind")

        if kind == "peer_init":
            username = msg["username"]
            conn_type = msg.get("type", "")

            if conn_type == ConnectionType.FILE_TRANSFER:
                # File transfer connection — route to TransferManager
                # PeerInit's token is often 0 for F connections; the handler
                # re-resolves from FileTransferInit, so a username pick is fine here.
                token = msg.get("token")
                if token is not None:
                    by_token = self.transfers.get_transfer_by_token(username, token)
                    transfer = by_token or self.transfers.find_active_transfer_for_user(username)
                    if transfer:
                        log.info(f"[client] Inbound file transfer connection from {username} (peer_init F)")
                        self._start_file_task(
                            by_token,  # only claim the transfer when the token named it
                            self.transfers.handle_file_transfer_connection(username, token, reader, writer),
                        )
                    else:
                        log.warning(f"[client] File transfer connection from {username} but no matching transfer")
                        writer.close()
                else:
                    writer.close()
                return

            # Regular P2P connection
            if username in self.peers:
                # Replace stale peer connection
                old = self.peers.pop(username)
                old.destroy()

            peer = PeerConnection(
                reader, writer, username,
                on_message=self._handle_peer_message,
                on_close=self._handle_peer_close,
            )
            peer.start_reading()
            self.peers[username] = peer

        elif kind == "pierce_firewall":
            # Inbound file transfer — peer connects to our listen port with transfer token
            token = msg.get("token")
            relay = self._upload_relays.pop(token, None) if token else None
            if relay is not None:
                # The relayed F connection for one of our uploads — checked first so
                # it never reaches the download-side token lookup.
                if relay.done():
                    writer.close()
                else:
                    relay.set_result((reader, writer))
                return
            if token:
                transfer = self.transfers.find_transfer_by_token(token)
                if transfer:
                    log.info(f"[client] Inbound file transfer via pierce_firewall from {transfer.username}")
                    self._start_file_task(
                        transfer,
                        self.transfers.handle_file_transfer_connection(
                            transfer.username, token, reader, writer, username_known=False,
                        ),
                    )
                else:
                    log.warning(f"[client] pierce_firewall with unknown token {token.hex()}")
                    writer.close()
            else:
                writer.close()

    async def _open_upload_connection(
        self, username: str, timeout: float = DEFAULT_PEER_TIMEOUT,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Open an F connection to a peer for one of our uploads: a direct connect
        (PeerInit type F, token 0) raced against a server-relayed one (ConnectToPeer
        type F; the peer connects to us with a PierceFirewall carrying the relay
        token). Returns the stream right after that greeting, ready for
        FileTransferInit."""
        relay = os.urandom(4)
        relayed: asyncio.Future = asyncio.get_running_loop().create_future()
        self._upload_relays[relay] = relayed

        async def direct():
            addr = await self._request_peer_address(username, timeout=timeout)
            if not addr.get("port"):
                raise ConnectionError("peer has no address")
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(addr["host"], addr["port"]), timeout=timeout,
            )
            try:
                writer.write(build_peer_init(
                    self.server.username or "", ConnectionType.FILE_TRANSFER, bytes(4),
                ))
                await writer.drain()
            except BaseException:
                writer.close()
                raise
            return reader, writer

        async def indirect():
            await self.server.connect_to_peer(relay, username, ConnectionType.FILE_TRANSFER)
            return await asyncio.wait_for(asyncio.shield(relayed), timeout=timeout)

        tasks = [asyncio.create_task(direct()), asyncio.create_task(indirect())]
        result = None
        errors: list[BaseException] = []
        try:
            pending = set(tasks)
            while pending and result is None:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task.cancelled():
                        continue
                    if task.exception() is not None:
                        errors.append(task.exception())
                    elif result is None:
                        result = task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                with contextlib.suppress(BaseException):
                    await task
            if self._upload_relays.get(relay) is relayed:
                del self._upload_relays[relay]
            if not relayed.done():
                relayed.cancel()
            # Close every connection that made it but isn't the one we keep.
            made = [t.result() for t in tasks
                    if t.done() and not t.cancelled() and t.exception() is None]
            if relayed.done() and not relayed.cancelled():
                made.append(relayed.result())
            for _, w in made:
                if result is None or w is not result[1]:
                    w.close()
        if result is None:
            raise ConnectionError(f"Cannot open file connection to {username}: {errors}")
        return result

    async def _on_upload_change(self, force: bool = False) -> None:
        """Upload state changed (force) or bytes moved (already throttled and
        coalesced by the UploadManager). The transfer broadcast carries downloads
        only, so there is nothing to push yet; this is the hook for wiring upload
        progress into the UI."""
        return None

    def _start_file_task(self, transfer: Transfer | None, coro) -> asyncio.Task:
        """Run a file-connection handler as a task the client keeps a reference to,
        and record it on the transfer (unless another handler already owns it) so
        TransferManager.abort() can cancel it."""
        task = asyncio.create_task(coro)
        self._file_tasks.add(task)
        task.add_done_callback(self._file_tasks.discard)
        if transfer is not None and (transfer.task is None or transfer.task.done()):
            transfer.task = task
        return task

    # --- Transfer callbacks ---

    async def _on_transfer_progress(self, transfer: Transfer) -> None:
        """Called during file download for progress updates (throttled to 500ms)."""
        now = time.monotonic()
        if now - self._last_broadcast < 0.5:
            return
        self._last_broadcast = now
        await self._sync_job_progress(transfer)
        await self._broadcast_transfers()

    async def _on_transfer_complete(self, transfer: Transfer) -> None:
        """Called when download completes or fails."""
        if transfer.state == TransferState.COMPLETED:
            await self.reputation.record_success(transfer.username)
        elif transfer.blame_peer:  # not when we gave up ourselves (cancel, another source won)
            await self.reputation.record_failure(transfer.username)
        await self._sync_job_progress(transfer)
        await self._broadcast_transfers()
        # Don't remove immediately — let poll_transfer see the final state.
        # The cleanup loop will remove terminal transfers after 60s.

    async def _sync_job_progress(self, transfer: Transfer) -> None:
        """Mirror transfer bytes onto the linked Job row so any UI that reads job.progress
        (TopBar, sidebar, dashboard activity) reflects real download progress. Uses a
        short-lived session — never the caller's session."""
        if not transfer.job_id or transfer.total_bytes <= 0:
            return
        try:
            from sqlalchemy import update
            from backend.database import async_session
            from backend.models.job import Job
            async with async_session() as s:
                await s.execute(
                    update(Job)
                    .where(Job.id == transfer.job_id)
                    .values(progress=transfer.received_bytes, total=transfer.total_bytes)
                )
                await s.commit()
        except Exception as e:
            log.debug("Job progress sync failed for %s: %s", transfer.job_id, e)

    async def _broadcast_transfers(self) -> None:
        """Broadcast current transfers to all WebSocket clients."""
        try:
            from backend.api.websocket import broadcast_transfer_progress
            await broadcast_transfer_progress(self.transfers.get_all_transfers())
        except Exception as e:
            log.debug("Transfer broadcast failed: %s", e)

    async def _peer_cleanup_loop(self) -> None:
        """Close idle peer connections to prevent fd leaks."""
        try:
            while True:
                await asyncio.sleep(120)
                # Find peers with no active transfers
                active_users = {t.username for t in self.transfers.transfers.values()}
                active_users |= self.uploads.active_usernames()  # keep their P connection
                idle = [u for u in list(self.peers) if u not in active_users]
                for username in idle:
                    peer = self.peers.pop(username, None)
                    if peer:
                        peer.destroy()
                if idle:
                    log.info(f"[client] Cleaned up {len(idle)} idle peer connections")
        except asyncio.CancelledError:
            return

    def destroy(self) -> None:
        """Tear down all connections."""
        if self._peer_cleanup_task and not self._peer_cleanup_task.done():
            self._peer_cleanup_task.cancel()
        if self._share_task and not self._share_task.done():
            self._share_task.cancel()
        self.uploads.destroy()
        for fut in self._upload_relays.values():
            if not fut.done():
                fut.cancel()
        self._upload_relays.clear()
        self.server.destroy()
        self.listener.destroy()
        self.transfers.destroy()
        for task in list(self._file_tasks):
            task.cancel()
        for peer in list(self.peers.values()):
            peer.destroy()
        self.peers.clear()
        self._search_results.clear()
        self._search_events.clear()
        self._peer_address_futures.clear()
