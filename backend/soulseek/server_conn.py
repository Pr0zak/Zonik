"""Server connection to server.slsknet.org — handles login, message dispatch, reconnect."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from backend.soulseek.protocol.stream import MessageStream
from backend.soulseek.protocol.server_messages import (
    build_login, build_set_wait_port, build_shared_folders_files,
    build_have_no_parents, build_set_status, build_get_peer_address,
    build_file_search, build_connect_to_peer, build_cant_connect_to_peer,
    parse_server_message,
)
from backend.soulseek.protocol.types import UserStatus

log = logging.getLogger(__name__)

DEFAULT_HOST = "server.slsknet.org"
DEFAULT_PORT = 2242
MAX_RECONNECT_DELAY = 300  # 5 minutes


class ServerConnection:
    """Manages the TCP connection to the Soulseek server."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        listen_port: int = 2234,
        on_message: Callable[[dict], Awaitable[None]] | None = None,
        on_disconnect: Callable[[], Awaitable[None]] | None = None,
    ):
        self.host = host
        self.port = port
        self.listen_port = listen_port
        self.on_message = on_message
        self.on_disconnect = on_disconnect

        self._stream: MessageStream | None = None
        self._read_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._credentials: tuple[str, str] | None = None
        self._reconnect_attempts = 0
        self.total_reconnects = 0
        self._auto_reconnect = True
        self._connected = False
        self.logged_in = False
        self.username: str | None = None
        self.connected_since: float | None = None

    @property
    def connected(self) -> bool:
        return self._connected and self._stream is not None

    async def connect(self) -> None:
        """Establish TCP connection to server."""
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self._stream = MessageStream(reader, writer)
        self._connected = True
        self._read_task = asyncio.create_task(self._read_loop())
        log.info(f"[server] Connected to {self.host}:{self.port}")

    async def login(self, username: str, password: str, timeout: float = 10.0) -> dict:
        """Login and wait for response. Returns login result dict."""
        self._credentials = (username, password)
        self.username = username

        login_future: asyncio.Future[dict] = asyncio.get_event_loop().create_future()

        original_handler = self.on_message

        async def login_handler(msg: dict):
            if msg.get("kind") == "login":
                if not login_future.done():
                    login_future.set_result(msg)
            if original_handler:
                await original_handler(msg)

        self.on_message = login_handler

        self._stream.write_message(build_login(username, password))
        await self._stream.drain()

        try:
            result = await asyncio.wait_for(login_future, timeout=timeout)
        finally:
            self.on_message = original_handler

        if not result.get("success"):
            raise ConnectionError(f"Login failed: {result.get('reason', 'unknown')}")

        import time
        self.logged_in = True
        self.connected_since = time.time()
        self._reconnect_attempts = 0

        # Post-login handshake
        await self._send(build_set_wait_port(self.listen_port))
        # Report real share counts from cached scan
        from backend.soulseek.shares import get_share_counts
        num_dirs, num_files = get_share_counts()
        if num_dirs == 0:
            num_dirs, num_files = 1, 1  # Minimum to avoid looking like a leecher
        await self._send(build_shared_folders_files(num_dirs, num_files))
        await self._send(build_have_no_parents(True))
        await self._send(build_set_status(UserStatus.ONLINE))

        log.info(f"[server] Logged in as {username}")
        return result

    async def connect_and_login(self, username: str, password: str) -> dict:
        """Connect + login in one call. Enables auto-reconnect."""
        await self.connect()
        result = await self.login(username, password)
        return result

    async def get_peer_address(self, username: str) -> None:
        await self._send(build_get_peer_address(username))

    async def file_search(self, token: bytes, query: str) -> None:
        await self._send(build_file_search(token, query))

    async def connect_to_peer(self, token: bytes, username: str, conn_type: str) -> None:
        await self._send(build_connect_to_peer(token, username, conn_type))

    async def cant_connect_to_peer(self, token: bytes, username: str) -> None:
        await self._send(build_cant_connect_to_peer(token, username))

    async def _send(self, data: bytes) -> None:
        if self._stream:
            self._stream.write_message(data)
            await self._stream.drain()

    async def _read_loop(self) -> None:
        """Read messages from server until disconnected."""
        try:
            while self._connected and self._stream:
                payload = await self._stream.read_message()
                if payload is None:
                    break

                try:
                    msg = parse_server_message(payload)
                    if msg and self.on_message:
                        await self.on_message(msg)
                except Exception as e:
                    log.error(f"[server] Error parsing message: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error(f"[server] Read loop error: {e}")
        finally:
            self._connected = False
            self.logged_in = False
            log.info("[server] Disconnected")
            if self.on_disconnect:
                await self.on_disconnect()
            if self._auto_reconnect and self._credentials:
                self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
            return
        delay = min(2 ** self._reconnect_attempts, MAX_RECONNECT_DELAY)
        self._reconnect_attempts += 1
        log.info(f"[server] Reconnecting in {delay}s (attempt {self._reconnect_attempts})")
        self._reconnect_task = asyncio.create_task(self._reconnect(delay))

    async def _reconnect(self, delay: float) -> None:
        await asyncio.sleep(delay)
        if not self._auto_reconnect or not self._credentials:
            return

        try:
            await self.connect()
            await self.login(*self._credentials)
            self.total_reconnects += 1
            log.info("[server] Reconnected successfully")
        except Exception as e:
            log.warning(f"[server] Reconnect failed: {e}")
            self._schedule_reconnect()

    def destroy(self) -> None:
        """Tear down the connection."""
        self._auto_reconnect = False
        self._connected = False
        self.logged_in = False

        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        if self._stream:
            self._stream.close()
            self._stream = None
