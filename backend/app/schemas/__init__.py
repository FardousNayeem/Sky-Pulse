"""API data-transfer objects. The HTTP contract lives here, nowhere else."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TopicSummary(BaseModel):
    name: str
    phrases: list[str]
    langs: list[str] = Field(default_factory=list, description="empty means any language")
    total_hits: int = 0


class CorpusStats(BaseModel):
    minutes_collected: int
    hours_collected: float
    posts_scanned: int
    matches_stored: int
    alerts: int
    terms_tracked: int = Field(default=0, description="distinct terms seen in the stream")
    samples_stored: int = 0
    trends_tracked: int = 0
    events_found: int = 0
    first_minute: int | None = None
    last_minute: int | None = None
    collecting: bool = Field(description="True if ingest flushed to disk in the last 5 minutes")
    lag_seconds: int | None = Field(
        default=None,
        description="How far the processed stream trails wall-clock. Rises while "
                    "catching up after a reconnect.",
    )
    ready_for_detection: bool = Field(
        description="True once the earliest horizon (fast, one hour) can score"
    )
    minutes_needed: int = Field(description="minutes until the earliest horizon is ready")
    horizons: list["HorizonStatus"] = Field(default_factory=list)


class SeriesPoint(BaseModel):
    t: int = Field(description="bucket start, unix seconds")
    hits: int
    total: int
    share: float
    coverage: float


class TopicSeries(BaseModel):
    topic: str
    bucket_minutes: int
    points: list[SeriesPoint]


class Alert(BaseModel):
    id: int
    subject: str = Field(description="the topic name or discovered term that spiked")
    kind: str = Field(description="'topic' (from topics.json) or 'term' (found in the stream)")
    mode: str = Field(description="the horizon that raised this alert: fast, mid or deep")
    bucket: int
    hits: int
    total: int
    share: float
    baseline: float
    zscore: float
    multiple: float
    terms: list[str]
    links: list[str] = Field(
        default_factory=list, description="most-shared URLs inside the spike"
    )
    confidence: float | None = Field(
        default=None,
        description="learned probability the spike holds rather than reverting; "
                    "null until a model has been fitted",
    )
    created_at: int


class Post(BaseModel):
    ts: int
    did: str
    rkey: str
    lang: str | None
    text: str
    url: str


class HorizonStatus(BaseModel):
    """One detection horizon, and whether enough has been collected to use it."""

    mode: str
    description: str
    bucket_minutes: int
    baseline_window: int
    z_threshold: float
    min_hits: int
    warmup_minutes: int = Field(
        description="(window + gap + 1) * bucket_minutes - collection needed before "
                    "the first bucket can be scored"
    )
    warmup_hours: float
    ready: bool
    minutes_remaining: int
    alerts: int


class Event(BaseModel):
    """A story: terms that spiked together, chained across windows."""

    key: str
    mode: str
    terms: list[str]
    first_bucket: int
    last_bucket: int
    buckets: int
    hits: int
    zscore: float
    confidence: float | None = None
    links: list[str] = Field(default_factory=list)

    story_did: str | None = None
    story_rkey: str | None = None
    story_ts: int | None = None
    story_text: str | None = None
    story_novelty: float | None = Field(
        default=None, description="1.0 means nothing like it had been said before"
    )
    story_url: str | None = None

    recurrence: float | None = Field(
        default=None, description="similarity to the closest earlier event"
    )
    recurs_from: str | None = Field(
        default=None, description="key of the earlier event this repeats, when it does"
    )


class TrendMatch(BaseModel):
    """One Bluesky trend, and the alert that found it first - if any did."""

    topic: str
    display_name: str
    category: str
    status: str
    post_count: int
    first_seen: int
    matched: bool
    match_basis: str = Field(
        default="", description="'subject' if the spiking word was the trend itself, "
                                "'terms' if its explanation was"
    )
    alert_id: int | None = None
    alert_subject: str | None = None
    alert_kind: str | None = None
    alert_mode: str | None = None
    alert_bucket: int | None = None
    lead_minutes: int | None = Field(
        default=None, description="positive means sky-pulse raised it before Bluesky "
                                  "listed it; negative means after"
    )


class BenchmarkReport(BaseModel):
    """How this detector does against the platform's own trending list."""

    trends_tracked: int
    matched: int
    coverage: float = Field(description="matched / trends_tracked")
    median_lead_minutes: float | None
    best_lead_minutes: int | None
    rows: list[TrendMatch]


class DetectionRun(BaseModel):
    ran: bool
    mode: str = ""
    kind: str = ""
    reason: str | None = None
    alerts_found: int = 0
    new_alerts: int = 0
    topics_scanned: int = 0
    bucket_minutes: int = 0
    z_threshold: float = 0.0
    minutes_remaining: int = 0
