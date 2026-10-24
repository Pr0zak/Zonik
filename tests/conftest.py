"""Point the app config at a throwaway location before any backend module that
creates the SQLite engine at import time gets imported (it would otherwise try
to create /opt/zonik/data). Tests that need the database ask for `db_ready`."""
import tempfile
from pathlib import Path

import backend.config as _config

_tmp = Path(tempfile.mkdtemp(prefix="zonik-tests-"))
_toml = _tmp / "zonik.toml"
_toml.write_text(
    f'[database]\npath = "{_tmp / "zonik.db"}"\n'
    f'[library]\ncover_cache_dir = "{_tmp / "covers"}"\nmusic_dir = "{_tmp / "music"}"\n'
    f'[soulseek]\nstaging_dir = "{_tmp / "staging"}"\ndownload_dir = "{_tmp / "downloads"}"\n'
    # Never multicast/bind from the suite's many app instances; tests opt in explicitly.
    '[discovery]\nenabled = false\n'
    # Most tests call the API anonymously; auth tests flip enforce on where they need it.
    '[auth]\nenforce = false\n'
)
_config.CONFIG_PATHS[:] = [_toml]


# --- Database + fake Soulseek client (opt-in fixtures) -----------------------
# Tests that need a real database request `db_ready`: it empties the temp SQLite
# file configured above and recreates every table with init_db(), so
# backend.database.async_session() works. `fake_slsk` installs a FakeClient as
# the process's native Soulseek client (see tests/fake_soulseek.py).
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db_ready():
    import backend.models  # noqa: F401  (registers every table on Base.metadata)
    from backend.database import Base, engine, init_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    yield


@pytest.fixture
def fake_slsk(monkeypatch, tmp_path):
    import backend.api.download as download
    import backend.soulseek as soulseek
    from fake_soulseek import FakeClient  # tests/ is on sys.path (rootdir conftest)

    client = FakeClient(tmp_path / "staging")
    monkeypatch.setattr(soulseek, "get_client", lambda: client)
    monkeypatch.setattr(download, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(download, "PEER_BUSY_WAIT", 0.05)

    async def no_broadcast(*_a, **_k):
        pass
    monkeypatch.setattr(download, "broadcast_job_update", no_broadcast)
    download.reset_download_semaphore()
    download.cancelled_jobs.clear()
    download.live_download_jobs.clear()
    yield client
    download.reset_download_semaphore()
    download.cancelled_jobs.clear()
    download.live_download_jobs.clear()
