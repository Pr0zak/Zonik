"""The job-cancel route only flags download jobs a task in this process owns.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_cancel.py
"""
from types import SimpleNamespace

import pytest

import backend.api.download as download
import backend.api.jobs as jobs


class FakeDB:
    def __init__(self, job):
        self.job = job
        self.committed = False

    async def execute(self, _query):
        return SimpleNamespace(scalar_one_or_none=lambda: self.job)

    async def commit(self):
        self.committed = True


def make_job(job_id, status="running"):
    return SimpleNamespace(id=job_id, type="download", status=status, result=None,
                           finished_at=None, progress=0, total=1)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    async def no_broadcast(_msg):
        pass
    monkeypatch.setattr(jobs, "broadcast_job_update", no_broadcast)
    download.cancelled_jobs.clear()
    download.live_download_jobs.clear()
    yield
    download.cancelled_jobs.clear()
    download.live_download_jobs.clear()


@pytest.mark.asyncio
async def test_cancel_flags_a_live_job():
    download.live_download_jobs.add("j1")
    db = FakeDB(make_job("j1"))
    assert (await jobs.cancel_job("j1", db)) == {"ok": True}
    assert db.committed and db.job.status == "failed"
    assert "j1" in download.cancelled_jobs


@pytest.mark.asyncio
async def test_cancel_of_stale_row_leaves_no_id_behind():
    db = FakeDB(make_job("stale", status="pending"))  # e.g. left over from before a restart
    assert (await jobs.cancel_job("stale", db)) == {"ok": True}
    assert db.job.status == "failed"
    assert download.cancelled_jobs == set()


def test_job_done_clears_both_sets():
    download.live_download_jobs.add("j2")
    download.cancelled_jobs.add("j2")
    download._job_done("j2")
    assert "j2" not in download.live_download_jobs and "j2" not in download.cancelled_jobs
