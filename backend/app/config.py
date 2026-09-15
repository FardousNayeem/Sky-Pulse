"""Single source of configuration. Override any field with an env var."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PULSE_", env_file=".env", extra="ignore")

    # storage
    database_path: Path = BACKEND_DIR / "data" / "pulse.db"
    model_path: Path = BACKEND_DIR / "data" / "model.json"
    topics_path: Path = BACKEND_DIR / "topics.json"

    # ingest
    jetstream_hosts: tuple[str, ...] = (
        "wss://jetstream.us-east.bsky.network/subscribe",
        "wss://jetstream.us-west.bsky.network/subscribe",
        "wss://jetstream2.us-east.bsky.network/subscribe",
    )
    collection: str = "app.bsky.feed.post"
    flush_seconds: float = 5.0
    max_text_length: int = 500
    max_cursor_age_seconds: int = 3600
    match_retention_days: int = 14

    # term discovery
    # A watchlist only finds what someone predicted, so terms are also taken
    # from the stream itself. Only the heaviest of each minute are stored: the
    # vocabulary of a firehose is unbounded, and a term outside the top of its
    # own minute has nowhere near the volume a spike needs.
    terms_enabled: bool = True
    term_capacity: int = 20_000          # distinct terms held in memory per flush
    term_top_per_minute: int = 400       # of those, how many reach disk
    term_min_hits_per_minute: int = 3    # below this a term is one person talking
    term_candidate_limit: int = 1500     # terms scored per detection pass
    term_retention_hours: int = 48

    # Sampled corpus. Terms are discovered, not declared, so there is no way to
    # know in advance which posts explain a spike. Keeping every post is about
    # 1.7 GB/day; a fixed fraction on short retention is a few tens of MB and
    # still leaves hundreds of posts behind anything worth reading about.
    sample_rate: float = 0.08
    sample_retention_hours: int = 6

    # Bluesky's own trending topics: public, unauthenticated, and the only
    # ground truth available for whether any of this detection is any good.
    trends_enabled: bool = True
    trends_url: str = "https://api.bsky.app/xrpc/app.bsky.unspecced.getTrends"
    trends_seconds: float = 300.0
    trends_limit: int = 25

    # housekeeping
    prune_seconds: float = 1800.0

    # detection
    # How often the collector scores what it has collected. Detection is
    # retroactive and takes tens of milliseconds, so this is a freshness knob,
    # not a cost one. Set to 0 to leave scoring to POST /api/detect.
    detect_seconds: float = 60.0

    # Bucket size, baseline length, z-threshold and the min-hits floor are
    # per-horizon and live in app/core/horizons.py, because warm-up is derived
    # from them and a single global value would fix the tool at one answer
    # speed. Coverage is the exception: it is a statement about the collector
    # rather than about any horizon, so every horizon shares it.
    min_coverage: float = 0.8

    # Confidence model. Fitting on a handful of rows produces a model that
    # describes those rows and nothing else, so training refuses below this.
    model_min_samples: int = 150
    model_min_positives: int = 20

    # api
    cors_origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")


@lru_cache
def get_settings() -> Settings:
    return Settings()
