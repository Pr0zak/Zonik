from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from functools import lru_cache

from pydantic import BaseModel

_log = logging.getLogger(__name__)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 3000
    secret_key: str = "change-me"
    # Empty by default: the web UI is served from this same app, and the phone, TV and watch
    # clients are native and ignore CORS entirely, so nothing legitimate needs a cross-origin
    # grant. The old "*" default was worse than it looked — Starlette echoes the requesting
    # origin when allow_credentials is on, so any page in any browser that could reach this
    # host could read every /api response, including the unauthenticated config endpoint that
    # returns third-party API keys. Add specific origins here if you front the API elsewhere.
    cors_origins: list[str] = []
    rate_limit_rps: float = 10.0
    rate_limit_burst: int = 30


class AuthConfig(BaseModel):
    # Grace mode while false: requests without credentials still run, as the owner (the first
    # admin), and are logged. Set true once every client (web, phone, TV, watch, Zata) logs in.
    enforce: bool = False
    # Web sessions slide: each use (at most every 5 min) pushes the expiry this far out.
    session_days: int = 90
    # Login lockout per (client IP, username): this many failures within lockout_minutes.
    login_max_failures: int = 5
    lockout_minutes: int = 5


class LibraryConfig(BaseModel):
    music_dir: str = "/music"
    cover_cache_dir: str = "/opt/zonik/cache/covers"
    naming_scheme: str = "{artist}/{album}/{track_number} - {title}"


class DatabaseConfig(BaseModel):
    backend: str = "sqlite"  # "sqlite" or "postgresql"
    path: str = "/opt/zonik/data/zonik.db"  # SQLite path
    url: str = ""  # PostgreSQL URL (e.g., postgresql+asyncpg://user:pass@host/db)


class RedisConfig(BaseModel):
    url: str = "redis://localhost:6379/0"


class SoulseekConfig(BaseModel):
    slskd_url: str = ""
    slskd_api_key: str = ""
    download_dir: str = "/downloads"  # legacy; no longer written to (see staging_dir)
    # Local per-job staging for native transfers: <staging_dir>/<job_id>/...
    # Finished files are moved into the library from here; only this dir is ever cleaned.
    staging_dir: str = "/opt/zonik/cache/staging"
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
    max_concurrent_downloads: int = 4  # Max simultaneous transfer attempts (others queue)
    search_min_interval_s: float = 8.0  # min gap between searches sent to the server
    searches_per_minute: int = 6  # hard cap; 15/min with bursts got our IP blocked (2026-10-17)
    max_concurrent_searches: int = 3  # Max download jobs in their search phase at once (others show "pending")
    # Ceiling for one transfer: the poller gives up after this long, and the client's
    # cleanup drops a TRANSFERRING entry with no data for this long. A transfer that
    # stops sending for 60 s still fails as stalled; a slow but steady one may finish.
    transfer_max_minutes: int = 30
    # Multi-source download settings
    parallel_sources: int = 1  # How many peers to download from simultaneously (1 = sequential)
    source_strategy: str = "first"  # "first" = keep first completed, "best" = wait for all and keep best quality
    share_library: bool = True  # Share real library with peers (false = report empty shares)
    # Serving uploads (only when share_library is on): files sent at once (never
    # more than one per peer; the rest wait in a queue), and a cap on the total
    # upload rate across all of them in KB/s (0 = unlimited).
    upload_slots: int = 2
    upload_speed_limit_kbps: int = 1024


class LidarrConfig(BaseModel):
    enabled: bool = False
    url: str = ""
    api_key: str = ""
    root_folder: str = "/music"


class LastfmConfig(BaseModel):
    api_key: str = ""
    write_api_key: str = ""
    write_api_secret: str = ""
    session_key: str = ""
    username: str = ""


class AnalysisConfig(BaseModel):
    enable_essentia: bool = True
    enable_clap: bool = True
    use_gpu: bool = False
    clap_model: str = "HTSAT-base"
    max_analysis_workers: int = 2


class SpotifyConfig(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class AppleMusicConfig(BaseModel):
    developer_token: str = ""


class StreamingConfig(BaseModel):
    max_concurrent_transcodes: int = 3
    transcode_cache_dir: str = "/opt/zonik/cache/transcodes"
    transcode_cache_max_mb: int = 500


class SubsonicConfig(BaseModel):
    server_name: str = "Zonik"
    # New-arrivals quota: guarantee this % of each Shuffle Mix is drawn from
    # recently-ADDED tracks (by created_at). 0 = off. shuffle_new_arrival_days
    # defines how recent "new" means.
    shuffle_new_arrival_percent: int = 0
    shuffle_new_arrival_days: int = 30
    # Unplayed quota: this % of each mix is drawn from tracks never played. 0 = off.
    shuffle_unplayed_percent: int = 0
    # Cooldown: leave out tracks played in the last N days (0 = off). Falls back to
    # them only when the rest of the library can't fill the mix.
    shuffle_cooldown_days: int = 0
    # Variety caps per mix. max_per_artist 0 = no limit.
    shuffle_max_per_artist: int = 2
    shuffle_one_per_album: bool = True
    # The same artist doesn't come back within this many tracks (0 = off).
    shuffle_artist_gap: int = 5


class AssistantConfig(BaseModel):
    enabled: bool = True
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-5-5"
    # Small, latency-sensitive calls (resolving "that song from ..." into
    # artist/title candidates) use a cheaper model.
    claude_fast_model: str = "claude-haiku-5-5"
    max_suggestions_per_call: int = 20
    w_artist_affinity: float = 0.25
    w_genre_match: float = 0.20
    w_lastfm_similar: float = 0.20
    # w_audio_match is ignored (kept so old configs still load): it was a constant 0.5.
    # w_clap_similarity weighs the CLAP similarity of a candidate's 30 s iTunes preview to the
    # taste centroid. The weights of the terms present for a candidate are renormalised to sum
    # to 1, so a candidate without a preview similarity is scored on the other five as before.
    w_audio_match: float = 0.15
    w_clap_similarity: float = 0.10
    w_popularity: float = 0.05
    w_novelty: float = 0.05
    # Bar for Last.fm global-chart entries (lastfm_top_tracks). Chart entries have no
    # Last.fm similarity score, so the usual 0.5 recommendation threshold is unreachable.
    # Overridable per task with "chart_min_score" in the task config.
    chart_min_score: float = 0.3
    # Download each top candidate's iTunes preview (<= 3 MB) during the recommendation refresh,
    # embed it with CLAP and score it against the taste centroid. Needs analysis.enable_clap.
    # Embeddings are cached per preview URL in preview_embeddings.
    clap_previews: bool = True
    # At most this many previews are scored per refresh (CPU CLAP: ~1 s each on a cache miss).
    clap_preview_limit: int = 100
    # AI feature toggles
    ai_reranking: bool = True
    ai_search: bool = True
    ai_playlist_gen: bool = True
    ai_explanations: bool = True
    ai_auto_tagging: bool = True
    ai_mood_tags: bool = True
    ai_insights: bool = True
    ai_duplicate_resolver: bool = True
    ai_download_advisor: bool = True  # only runs when a /search request asks (ai=true)
    ai_track_resolver: bool = True  # AI candidates for vague catalog/voice searches
    ai_playlist_curator: bool = True
    # Usage/cost accounting — write one ai_usage row per Claude API call.
    # Turning this off keeps the in-memory session counters but stops the DB writes.
    track_ai_usage: bool = True
    # Optional pricing overrides: model-id -> [input, output] USD per 1M tokens.
    # Consulted before the built-in snapshot in backend/services/ai/pricing.py, so
    # rates can be corrected without a code change when Anthropic's pricing moves.
    model_pricing: dict[str, list[float]] = {}


class Settings(BaseModel):
    server: ServerConfig = ServerConfig()
    auth: AuthConfig = AuthConfig()
    library: LibraryConfig = LibraryConfig()
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    soulseek: SoulseekConfig = SoulseekConfig()
    lidarr: LidarrConfig = LidarrConfig()
    lastfm: LastfmConfig = LastfmConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    spotify: SpotifyConfig = SpotifyConfig()
    apple_music: AppleMusicConfig = AppleMusicConfig()
    streaming: StreamingConfig = StreamingConfig()
    subsonic: SubsonicConfig = SubsonicConfig()
    assistant: AssistantConfig = AssistantConfig()


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
            settings = Settings(**data)
            if settings.server.secret_key == "change-me":
                _log.warning("Using default secret_key 'change-me' — set server.secret_key in zonik.toml for production")
            return settings
    return Settings()
