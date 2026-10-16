"""Keep imports of backend.database off the production path (/opt/zonik/data)."""
import tempfile
from pathlib import Path

from backend import config

_settings = config.Settings(
    database=config.DatabaseConfig(path=str(Path(tempfile.mkdtemp(prefix="zonik-test-")) / "test.db"))
)
config.get_settings = lambda: _settings
