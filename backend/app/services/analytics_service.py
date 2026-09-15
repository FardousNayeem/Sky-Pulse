"""Read-side use cases: corpus stats, per-topic series, posts behind a spike."""
from __future__ import annotations

import time

from app.config import Settings
from app.db.repositories import (
    AlertsRepository,
    CountsRepository,
    EventsRepository,
    MatchesRepository,
    MetaRepository,
    SamplesRepository,
    TermsRepository,
    TrendsRepository,
)
from app.schemas import CorpusStats, Post, SeriesPoint, TopicSeries, TopicSummary
from app.services.horizon_service import earliest_warmup_minutes, horizon_statuses
from app.services.topic_service import TopicService

BSKY_POST_URL = "https://bsky.app/profile/{did}/post/{rkey}"
LIVE_WINDOW_SECONDS = 300


class AnalyticsService:
    def __init__(
        self,
        counts: CountsRepository,
        matches: MatchesRepository,
        alerts: AlertsRepository,
        meta: MetaRepository,
        terms: TermsRepository,
        samples: SamplesRepository,
        trends: TrendsRepository,
        events: EventsRepository,
        topics: TopicService,
        settings: Settings,
    ) -> None:
        self._counts = counts
        self._matches = matches
        self._alerts = alerts
        self._meta = meta
        self._terms = terms
        self._samples = samples
        self._trends = trends
        self._events = events
        self._topics = topics
        self._settings = settings

    def stats(self) -> CorpusStats:
        summary = self._counts.summary()
        minutes = summary["minutes_collected"]
        # Readiness is the earliest horizon, not the deepest one. The dashboard
        # has something to show an hour in; it should not claim otherwise for
        # nine because `deep` is still warming.
        needed = earliest_warmup_minutes()
        horizons = horizon_statuses(minutes, self._alerts.counts_by_mode())
        last = summary["last_minute"]
        now = time.time()
        heartbeat = self._meta.get("last_flush_at")
        return CorpusStats(
            minutes_collected=minutes,
            hours_collected=round(minutes / 60, 2),
            posts_scanned=summary["posts_scanned"],
            matches_stored=self._matches.count(),
            alerts=self._alerts.count(),
            terms_tracked=self._terms.distinct_terms(),
            samples_stored=self._samples.count(),
            trends_tracked=self._trends.count(),
            events_found=self._events.count(),
            first_minute=summary["first_minute"],
            last_minute=last,
            collecting=bool(heartbeat and (now - int(heartbeat)) < LIVE_WINDOW_SECONDS),
            lag_seconds=int(now - last) if last else None,
            ready_for_detection=minutes >= needed,
            minutes_needed=max(0, needed - minutes),
            horizons=horizons,
        )

    def topics(self) -> list[TopicSummary]:
        totals = self._counts.topic_totals()
        return [
            TopicSummary(name=t.name, phrases=list(t.phrases), langs=list(t.langs),
                         total_hits=totals.get(t.name, 0))
            for t in self._topics.load()
        ]

    def series(self, topic: str, bucket_minutes: int, limit: int) -> TopicSeries:
        buckets = self._counts.series(topic, bucket_minutes * 60, limit)
        return TopicSeries(
            topic=topic,
            bucket_minutes=bucket_minutes,
            points=[
                SeriesPoint(
                    t=b.start, hits=b.hits, total=b.total,
                    share=b.share, coverage=round(b.coverage, 3),
                )
                for b in buckets
            ],
        )

    def term_series(self, term: str, bucket_minutes: int, limit: int) -> TopicSeries:
        """Share of conversation over time for a discovered term.

        Reuses the topic series shape: a term and a topic are the same kind of
        measurement, counted differently.
        """
        bucket_seconds = bucket_minutes * 60
        totals, coverage = self._counts.bucket_frame(bucket_seconds)
        buckets = self._terms.buckets_for(
            [term], bucket_seconds, totals, coverage, bucket_minutes
        ).get(term, [])
        return TopicSeries(
            topic=term,
            bucket_minutes=bucket_minutes,
            points=[
                SeriesPoint(t=b.start, hits=b.hits, total=b.total,
                            share=b.share, coverage=round(b.coverage, 3))
                for b in buckets[-limit:]
            ],
        )

    def term_posts(self, term: str, limit: int, start: int | None, end: int | None) -> list[Post]:
        """Sampled posts mentioning a term.

        These come from the sample, not the full stream, so the list is a
        fraction of what was actually posted. It is enough to read what
        happened, which is what it is for.
        """
        if start is None or end is None:
            end = int(time.time())
            start = end - self._settings.sample_retention_hours * 3600
        rows = self._samples.containing(term, start, end, limit)
        return [
            Post(
                ts=r["ts"], did=r["did"], rkey=r["rkey"], lang=r["lang"], text=r["text"],
                url=BSKY_POST_URL.format(did=r["did"], rkey=r["rkey"]),
            )
            for r in rows
        ]

    def posts(self, topic: str, limit: int, start: int | None, end: int | None) -> list[Post]:
        rows = (
            self._matches.in_window(topic, start, end, limit)
            if start is not None and end is not None
            else self._matches.recent(topic, limit)
        )
        return [
            Post(
                ts=r["ts"], did=r["did"], rkey=r["rkey"], lang=r["lang"], text=r["text"],
                url=BSKY_POST_URL.format(did=r["did"], rkey=r["rkey"]),
            )
            for r in rows
        ]
