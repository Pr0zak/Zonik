"""LAN discovery: mDNS/DNS-SD `_zonik._tcp.local.` plus a UDP probe responder.

Started from the zonik-web lifespan only (never the arq worker). Everything here is best
effort: a missing multicast route, a taken UDP port or a zeroconf error logs a warning and
the server carries on. Registration runs in a background task so mDNS probing never delays
startup.

UDP probe: a datagram whose payload starts with `ZONIK?` gets a unicast JSON reply
{"zonik":1,"name":…,"version":…,"url":…} to the sender, at most RATE_PER_SEC per source IP.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time

from backend.config import get_settings

log = logging.getLogger(__name__)

SERVICE_TYPE = "_zonik._tcp.local."
PROBE_PREFIX = b"ZONIK?"
RATE_PER_SEC = 5


def server_name() -> str:
    s = get_settings()
    return (s.discovery.name or "").strip() or s.subsonic.server_name or "Zonik"


def _version() -> str:
    from backend.api.config_api import _get_version
    return _get_version()


def _usable_ipv4(ip: str) -> bool:
    return bool(ip) and not ip.startswith("127.") and not ip.startswith("169.254.") and ip != "0.0.0.0"


def primary_ipv4() -> str | None:
    """The IPv4 the default route leaves from (a UDP connect sends nothing), else the first
    non-loopback interface address, else None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.254.254.254", 1))
            ip = s.getsockname()[0]
        if _usable_ipv4(ip):
            return ip
    except OSError:
        pass
    ips = host_ipv4s()
    return ips[0] if ips else None


def host_ipv4s() -> list[str]:
    """Non-loopback, non-link-local IPv4 addresses of this host."""
    out: list[str] = []
    try:
        import ifaddr
        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if isinstance(ip.ip, str) and _usable_ipv4(ip.ip) and ip.ip not in out:
                    out.append(ip.ip)
    except Exception as e:  # ifaddr comes with zeroconf; tolerate it missing or failing
        log.debug("discovery: interface scan failed: %r", e)
    return out


def advertise_url() -> str | None:
    """discovery.advertise_url, else http://<primary LAN IPv4>:<server.port>; None if unknown."""
    s = get_settings()
    configured = (s.discovery.advertise_url or "").strip().rstrip("/")
    if configured:
        return configured
    ip = primary_ipv4()
    return f"http://{ip}:{s.server.port}" if ip else None


def probe_reply() -> bytes:
    return json.dumps({"zonik": 1, "name": server_name(), "version": _version(),
                       "url": advertise_url()}).encode()


class ProbeProtocol(asyncio.DatagramProtocol):
    """Answers `ZONIK?` datagrams; ignores everything else."""

    def __init__(self):
        self.transport: asyncio.DatagramTransport | None = None
        self._hits: dict[str, list[float]] = {}

    def connection_made(self, transport):
        self.transport = transport

    def _allowed(self, ip: str) -> bool:
        now = time.monotonic()
        if len(self._hits) > 1000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 1.0}
        recent = [t for t in self._hits.get(ip, []) if now - t < 1.0]
        if len(recent) >= RATE_PER_SEC:
            self._hits[ip] = recent
            return False
        recent.append(now)
        self._hits[ip] = recent
        return True

    def datagram_received(self, data: bytes, addr):
        if not data.startswith(PROBE_PREFIX) or self.transport is None:
            return
        if not self._allowed(addr[0]):
            return
        try:
            self.transport.sendto(probe_reply(), addr)
        except Exception as e:
            log.debug("discovery: probe reply to %s failed: %r", addr[0], e)

    def error_received(self, exc):
        log.debug("discovery: UDP error: %r", exc)


class Discovery:
    """Owns the zeroconf registration and the UDP responder for one app lifespan."""

    def __init__(self):
        self.azc = None
        self.info = None
        self.registered = False
        self.udp_transport: asyncio.DatagramTransport | None = None
        self._task: asyncio.Task | None = None

    async def start(self, *, udp_host: str = "0.0.0.0", udp_port: int | None = None) -> None:
        settings = get_settings()
        port = settings.discovery.udp_port if udp_port is None else udp_port
        await self.start_udp(udp_host, port)
        self._task = asyncio.create_task(self._register_mdns())

    async def start_udp(self, host: str, port: int) -> None:
        try:
            loop = asyncio.get_running_loop()
            self.udp_transport, _ = await loop.create_datagram_endpoint(
                ProbeProtocol, local_addr=(host, port), family=socket.AF_INET)
            log.info("discovery: UDP probe responder on %s:%s", host, port)
        except Exception as e:
            self.udp_transport = None
            log.warning("discovery: UDP probe responder not started on %s:%s: %r", host, port, e)

    def _service_info(self):
        from zeroconf.asyncio import AsyncServiceInfo
        settings = get_settings()
        name = server_name()
        url = advertise_url() or ""
        ips = host_ipv4s()
        primary = primary_ipv4()
        if primary and primary not in ips:
            ips.insert(0, primary)
        host = socket.gethostname().split(".")[0] or "zonik"
        safe_name = name.replace(".", " ")[:63] or "Zonik"
        return AsyncServiceInfo(
            SERVICE_TYPE,
            f"{safe_name}.{SERVICE_TYPE}",
            port=settings.server.port,
            properties={"version": _version(), "name": name, "path": "/", "scheme": "http",
                        "url": url, "api": "1"},
            addresses=[socket.inet_aton(ip) for ip in ips],
            server=f"{host}.local.",
        )

    async def _register_mdns(self) -> None:
        try:
            from zeroconf import IPVersion
            from zeroconf.asyncio import AsyncZeroconf
            self.info = self._service_info()
            if not self.info.addresses:
                log.warning("discovery: no LAN IPv4 address found, mDNS not registered")
                return
            self.azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            await (await self.azc.async_register_service(self.info, allow_name_change=True))
            self.registered = True
            log.info("discovery: mDNS registered %s", self.info.name)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("discovery: mDNS registration failed: %r", e)

    async def _unregister(self) -> None:
        await (await self.azc.async_unregister_service(self.info))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self.azc is not None:
            try:
                if self.registered and self.info is not None:
                    await asyncio.wait_for(self._unregister(), 3)
            except Exception as e:
                log.debug("discovery: mDNS unregister failed: %r", e)
            try:
                await asyncio.wait_for(self.azc.async_close(), 3)
            except Exception as e:
                log.debug("discovery: zeroconf close failed: %r", e)
            self.azc = None
            self.registered = False
        if self.udp_transport is not None:
            self.udp_transport.close()
            self.udp_transport = None


async def start_discovery() -> Discovery | None:
    """Start discovery when enabled; never raises."""
    if not get_settings().discovery.enabled:
        return None
    d = Discovery()
    try:
        await d.start()
    except Exception as e:
        log.warning("discovery: not started: %r", e)
    return d


async def stop_discovery(d: Discovery | None) -> None:
    if d is None:
        return
    try:
        await d.stop()
    except Exception as e:
        log.debug("discovery: shutdown error: %r", e)
