from __future__ import annotations

import tomllib
from pathlib import Path
from functools import lru_cache

from pydantic import BaseModel


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 3000
    secret_key: str = "change-me"


class LibraryConfig(BaseModel):
    music_dir: str = "/music"
    cover_cache_dir: str = "/opt/zonik/cache/covers"
    naming_scheme: str = "{artist}/{album}/{track_number} - {title}"


class DatabaseConfig(BaseModel):
    path: str = "/opt/zonik/data/zonik.db"


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"


class SoulseekConfig(BaseModel):
    slskd_url: str = ""
    slskd_api_key: str = ""
    download_dir: str = "/downloads"
    preferred_formats: list[str] = ["flac", "wav", "mp3"]
    min_file_size_mb: int = 3
    max_workers: int = 4
    # Native client settings
    username: str = ""
    password: str = ""
    listen_port: int = 2234
    server_host: str = "server.slsknet.org"
    server_port: int = 2242
    use_native: bool = False
    max_concurrent_downloads: int = 4  # Max simultaneous download jobs (others queue)
    # Multi-source download settings
    parallel_sources: int = 1  # How many peers to download from simultaneously (1 = sequential)
    source_strategy: str = "first"  # "first" = keep first completed, "best" = wait for all and keep best quality
    share_library: bool = True  # Share real library with peers (false = report empty shares)


class LidarrConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    root_folder: str = "/music"


class LastfmConfig(BaseModel):
    api_key: str = ""
    write_api_key: str = ""
    write_api_secret: str = ""


class AnalysisConfig(BaseModel):
    enable_essentia: bool = True
    enable_clap: bool = True
    use_gpu: bool = False
    clap_model: str = "HTSAT-base"
    max_analysis_workers: int = 2


class SubsonicConfig(BaseModel):
    server_name: str = "Zonik"


class Settings(BaseModel):
    server: ServerConfig = ServerConfig()
    library: LibraryConfig = LibraryConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    soulseek: SoulseekConfig = SoulseekConfig()
    lidarr: LidarrConfig = LidarrConfig()
    lastfm: LastfmConfig = LastfmConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    subsonic: SubsonicConfig = SubsonicConfig()


CONFIG_PATHS = [
    Path("zonik.toml"),
    Path("/etc/zonik/zonik.toml"),
]


@lru_cache
def get_settings() -> Settings:
    for path in CONFIG_PATHS:
        if path.exists():
            with open(path, "rb") as f:
                data = tomllib.load(f)
            return Settings(**data)
    return Settings()
