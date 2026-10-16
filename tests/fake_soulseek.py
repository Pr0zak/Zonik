"""A stand-in for backend.soulseek.client.SoulseekClient, for download-flow tests.

Search returns canned results. download() returns a real Transfer that a fake
uploader task drives according to the peer's scripted behaviour:

    "complete"     connects, sends the file, COMPLETED with a save_path
    "fail"         the peer denies the request (FAILED)
    "stall"        connects, sends nothing more
    "queue"        stays QUEUED (never starts)
    "unreachable"  download() itself raises ConnectionRefusedError
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from backend.soulseek.client import PeerBusy
from backend.soulseek.protocol.types import FileInfo, SearchResult, TransferState
from backend.soulseek.transfer import Transfer

MB = 1024 * 1024


def result(username: str, filename: str, size: int = 40 * MB, speed: int = 2_000_000,
           slots_free: bool = True) -> SearchResult:
    return SearchResult(username=username, token="t", files=[FileInfo(filename=filename, size=size)],
                        slots_free=slots_free, avg_speed=speed)


class FakeTransfers:
    def __init__(self):
        self.table: dict[tuple[str, str], Transfer] = {}
        self.aborted: list[tuple[str, str, bool]] = []  # (username, error, blame_peer)
        self.discarded: list[str] = []

    def add(self, t: Transfer) -> None:
        self.table[(t.username, t.filename)] = t

    def is_tracked(self, t: Transfer) -> bool:
        return self.table.get((t.username, t.filename)) is t

    def abort(self, t: Transfer, error: str, *, blame_peer: bool = True) -> bool:
        if t.state == TransferState.COMPLETED:
            return False
        t.state = TransferState.FAILED
        t.error = error
        t.blame_peer = blame_peer
        if self.table.get((t.username, t.filename)) is t:
            del self.table[(t.username, t.filename)]
        self.aborted.append((t.username, error, blame_peer))
        return True

    def discard_job(self, job_id: str) -> None:
        self.discarded.append(job_id)

    def get_all_transfers(self) -> list:
        return []


class FakeReputation:
    def __init__(self):
        self.failures: list[str] = []

    async def record_failure(self, username: str) -> None:
        self.failures.append(username)

    async def record_success(self, username: str) -> None:
        pass

    async def get_score_adjustment(self, username: str) -> int:
        return 0


class FakeClient:
    def __init__(self, staging: Path):
        self.staging = Path(staging)
        self.logged_in = True
        self.results: list[SearchResult] = []
        self.behaviour: dict[str, str] = {}  # username -> scripted behaviour
        self.searches: list[str] = []
        self.downloads: list[str] = []  # usernames, in the order download() was called
        self.transfers = FakeTransfers()
        self.reputation = FakeReputation()
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._uploaders: list[asyncio.Task] = []

    async def search(self, query: str, timeout: float = 0, max_responses: int = 50) -> list[SearchResult]:
        self.searches.append(query)
        return list(self.results)

    def slot(self, username: str) -> asyncio.Semaphore:
        return self._slots.setdefault(username, asyncio.Semaphore(1))

    @asynccontextmanager
    async def peer_slot(self, username: str, timeout: float | None = None):
        sem = self.slot(username)
        try:
            await asyncio.wait_for(sem.acquire(), timeout)
        except asyncio.TimeoutError:
            raise PeerBusy(username) from None
        try:
            yield
        finally:
            sem.release()

    async def download(self, username: str, filename: str, job_id: str | None = None) -> Transfer:
        self.downloads.append(username)
        how = self.behaviour.get(username, "complete")
        if how == "unreachable":
            raise ConnectionRefusedError(f"{username} unreachable")
        t = Transfer(username=username, filename=filename, job_id=job_id)
        t.state = TransferState.QUEUED
        self.transfers.add(t)
        self._uploaders.append(asyncio.create_task(self._upload(t, how)))
        return t

    async def _upload(self, t: Transfer, how: str) -> None:
        await asyncio.sleep(0.02)
        if t.state == TransferState.FAILED:  # aborted meanwhile
            return
        if how == "fail":
            t.state = TransferState.FAILED
            t.error = "Denied"
        elif how == "stall":
            t.state = TransferState.CONNECTED
            t.total_bytes = 1000
        elif how == "complete":
            t.state = TransferState.TRANSFERRING
            t.total_bytes = 1000
            t.received_bytes = 1000
            path = self.staging / (t.job_id or "nojob") / t.filename.replace("\\", "_")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * 1000)
            t.save_path = str(path)
            t.state = TransferState.COMPLETED
        # "queue": stays QUEUED
