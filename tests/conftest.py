"""Point the app config at a throwaway location before any backend module that
creates the SQLite engine at import time gets imported (it would otherwise try
to create /opt/zonik/data). No test here opens a database connection."""
import tempfile
from pathlib import Path

import backend.config as _config

_tmp = Path(tempfile.mkdtemp(prefix="zonik-tests-"))
_toml = _tmp / "zonik.toml"
_toml.write_text(
    f'[database]\npath = "{_tmp / "zonik.db"}"\n'
    f'[library]\ncover_cache_dir = "{_tmp / "covers"}"\nmusic_dir = "{_tmp / "music"}"\n'
    f'[soulseek]\nstaging_dir = "{_tmp / "staging"}"\ndownload_dir = "{_tmp / "downloads"}"\n'
)
_config.CONFIG_PATHS[:] = [_toml]
