"""cleanup_download_dir only sweeps stale per-job folders in Zonik's staging dir.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_cleanup.py
"""
import os
import time
from types import SimpleNamespace

import pytest

import backend.soulseek as soulseek_pkg
import backend.services.scanner as scanner
from backend.config import Settings, SoulseekConfig


def _settings(staging, download_dir):
    return Settings(soulseek=SoulseekConfig(staging_dir=str(staging), download_dir=str(download_dir)))


def _age(path, hours):
    t = time.time() - hours * 3600
    os.utime(path, (t, t))


def _make_job(staging, name, hours_old, files=(("song.flac", b"x" * 10),)):
    d = staging / name
    d.mkdir(parents=True)
    for fname, data in files:
        f = d / fname
        f.write_bytes(data)
        _age(f, hours_old)
    _age(d, hours_old)
    return d


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    nas = tmp_path / "nas"
    staging.mkdir()
    nas.mkdir()
    monkeypatch.setattr(scanner, "get_settings", lambda: _settings(staging, nas))
    monkeypatch.setattr(soulseek_pkg, "_client", None)
    return staging, nas


def test_removes_only_stale_job_folders(dirs):
    staging, nas = dirs
    stale = _make_job(staging, "job-old", hours_old=30)
    fresh = _make_job(staging, "job-new", hours_old=0.1)
    # zero-byte file just opened by a live transfer: must survive
    zero = _make_job(staging, "job-zero", hours_old=0, files=(("open.flac", b""),))
    out = scanner.cleanup_download_dir(max_age_hours=24)
    assert out["removed"] == 1 and out["freed_bytes"] == 10
    assert not stale.exists()
    assert fresh.exists() and zero.exists()


def test_recent_hour_is_protected_even_with_tiny_max_age(dirs):
    staging, _ = dirs
    recent = _make_job(staging, "job-recent", hours_old=0.5)
    scanner.cleanup_download_dir(max_age_hours=0)
    assert recent.exists()


def test_one_recent_file_keeps_old_folder(dirs):
    staging, _ = dirs
    d = _make_job(staging, "job-mixed", hours_old=30)
    (d / "new.flac").write_bytes(b"y")  # touched now
    scanner.cleanup_download_dir(max_age_hours=24)
    assert d.exists()


def test_skips_paths_owned_by_active_transfer(dirs, monkeypatch):
    staging, _ = dirs
    d = _make_job(staging, "job-live", hours_old=30)
    fake_tm = SimpleNamespace(active_paths=lambda: [str(d / "song.flac")])
    monkeypatch.setattr(soulseek_pkg, "_client", SimpleNamespace(transfers=fake_tm))
    scanner.cleanup_download_dir(max_age_hours=24)
    assert d.exists()


def test_never_touches_nas_download_dir(dirs):
    staging, nas = dirs
    other = nas / "someone-elses.nfo"
    other.write_bytes(b"")
    _age(other, 100)
    scanner.cleanup_download_dir(max_age_hours=24)
    assert other.exists()


def test_refuses_staging_overlapping_download_dir(tmp_path, monkeypatch):
    nas = tmp_path / "nas"
    nas.mkdir()
    victim = nas / "old.flac"
    victim.write_bytes(b"z")
    _age(victim, 100)
    monkeypatch.setattr(soulseek_pkg, "_client", None)
    for staging in (nas, tmp_path):  # same dir, and a parent of it
        monkeypatch.setattr(scanner, "get_settings", lambda s=staging: _settings(s, nas))
        assert scanner.cleanup_download_dir(max_age_hours=24)["removed"] == 0
    assert victim.exists()


def test_symlink_in_staging_is_not_followed(dirs, tmp_path):
    staging, _ = dirs
    outside = tmp_path / "outside"
    outside.mkdir()
    keep = outside / "keep.flac"
    keep.write_bytes(b"k")
    _age(keep, 100)
    (staging / "link").symlink_to(outside, target_is_directory=True)
    scanner.cleanup_download_dir(max_age_hours=24)
    assert keep.exists()
