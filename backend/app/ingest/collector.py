"""Ingest orchestration: stream -> match -> discover -> buffered write."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time

from app.config import Settings
from app.core.matcher import TopicMatcher
from app.core.terms import TopTerms, extract_terms
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
from app.ingest.jetstream import JetstreamClient, PostEvent
from app.ingest.trends import fetch_trends
from app.services.detection_service import DetectionService
from app.services.event_service import EventService

log = logging.getLogger("pulse.collector")
CURSOR_KEY = "cursor_time_us"
HEARTBEAT_KEY = "last_flush_at"
REPORT_SECONDS = 60


class WriteBuffer:
    """Accumulates in memory so SQLite sees one batch every few seconds,
    not 40 individual writes per second."""

    def __init__(self) -> None:
        self.minute_totals: dict[int, int] = {}
        self.topic_counts: dict[tuple[int, str], int] = {}
        self.term_counts: dict[tuple[int, str], int] = {}
        self.matches: list[tuple] = []
        self.samples: list[tuple] = []

    def add_post(self, minute: int) -> None:
        self.minute_totals[minute] = self.minute_totals.get(minute, 0) + 1

    def add_match(self, minute: int, topic: str, event: PostEvent, max_text: int) -> None:
        key = (minute, topic)
        self.topic_counts[key] = self.topic_counts.get(key, 0) + 1
        self.matches.append((
            event.timestamp, topic, event.did, event.rkey, event.lang,
            event.text[:max_text], " ".join(event.links),
        ))

    def add_sample(self, event: PostEvent, max_text: int) -> None:
        self.samples.append((
            event.timestamp, event.did, event.rkey, event.lang,
            event.text[:max_text], " ".join(event.links),
        ))

    def add_terms(self, minute: int, counts: dict[str, int]) -> None:
        for term, hits in counts.items():
            key = (minute, term)
            self.term_counts[key] = self.term_counts.get(key, 0) + hits

    def is_empty(self) -> bool:
        return not (
            self.minute_totals or self.topic_counts or self.term_counts
            or self.matches or self.samples
        )

    def clear(self) -> None:
        self.minute_totals.clear()
        self.topic_counts.clear()
        self.term_counts.clear()
        self.matches.clear()
        self.samples.clear()


class Collector:
    def __init__(
        self,
        connection: sqlite3.Connection,
        matcher: TopicMatcher,
        settings: Settings,
    ) -> None:
        self._db = connection
        self._matcher = matcher
        self._settings = settings
        self._counts = CountsRepository(connection)
        self._matches = MatchesRepository(connection)
        self._meta = MetaRepository(connection)
        self._terms_repo = TermsRepository(connection)
        self._samples = SamplesRepository(connection)
        self._trends = TrendsRepository(connection)
        self._detection = DetectionService(
            self._counts, self._matches, AlertsRepository(connection),
            self._terms_repo, self._samples, settings,
        )
        self._events = EventService(
            AlertsRepository(connection), EventsRepository(connection),
            self._samples, settings,
        )
        self._buffer = WriteBuffer()

        # Terms are counted a whole minute at a time. The top of a minute is
        # only knowable once the minute is over, so they cannot ride the
        # five-second flush the way counters do.
        self._terms = TopTerms(settings.term_capacity)
        self._term_minute: int | None = None

        # Deterministic sampling rather than random: every Nth post is uniform
        # over the stream, reproducible, and costs one modulo.
        self._sample_every = max(1, round(1 / settings.sample_rate)) if settings.sample_rate else 0

        self.posts_scanned = 0
        self.matches_found = 0
        self.terms_written = 0

    # --------------------------------------------------------------- writing

    def _roll_terms(self, minute: int | None) -> None:
        """Close off the minute being counted and queue its heaviest terms."""
        if self._term_minute is not None and len(self._terms):
            top = self._terms.top(
                self._settings.term_top_per_minute,
                self._settings.term_min_hits_per_minute,
            )
            self._buffer.add_terms(self._term_minute, top)
            self.terms_written += len(top)
        self._terms.clear()
        self._term_minute = minute

    def _flush(self, cursor: int | None) -> None:
        if self._buffer.is_empty() and cursor is None:
            return
        with self._db:
            self._counts.bulk_add(self._buffer.minute_totals, self._buffer.topic_counts)
            self._matches.bulk_add(self._buffer.matches)
            self._terms_repo.bulk_add(self._buffer.term_counts)
            self._samples.bulk_add(self._buffer.samples)
            # Wall-clock heartbeat. Event timestamps lag while catching up after
            # a reconnect, so they cannot tell us whether ingest is alive.
            self._meta.set(HEARTBEAT_KEY, int(time.time()))
            if cursor is not None:
                self._meta.set(CURSOR_KEY, cursor)
        self._buffer.clear()

    # ---------------------------------------------------------- housekeeping

    def _detect(self) -> None:
        """Score everything collected so far, at every horizon that is ready.

        Runs inline between flushes rather than in a task: it shares the writer
        connection, so serialising it with ingest is simpler than coordinating
        two writers. A failure here must never take down collection - the data
        is on disk either way, and the next pass will score it.
        """
        try:
            for run in self._detection.run_all():
                if run.new_alerts:
                    log.info("%s/%s: %s new alert(s)", run.mode, run.kind, run.new_alerts)
            # Grouping runs after scoring because it groups what scoring found.
            self._events.rebuild_all()
        except Exception:  # noqa: BLE001 - detection is not worth losing ingest over
            log.exception("detection pass failed; ingest continues")

    def prune(self) -> int:
        """Drop stored text past its retention. Counters are never pruned.

        The three corpora age at different rates because they cost different
        amounts: minute counters are tiny and permanent, topic matches are
        worth two weeks, and the term sample is large and only has to outlive
        the deepest detection window.
        """
        now = int(time.time())
        settings = self._settings
        with self._db:
            matches = self._matches.prune_before(now - settings.match_retention_days * 86400)
            samples = self._samples.prune_before(now - settings.sample_retention_hours * 3600)
            terms = self._terms_repo.prune_before(now - settings.term_retention_hours * 3600)
        removed = matches + samples + terms
        if removed:
            log.info("pruned %s matches, %s samples, %s term-minutes", matches, samples, terms)
        return removed

    async def _poll_trends(self) -> None:
        """Record what Bluesky itself is calling a trend.

        Off-thread because the fetch is blocking and the socket has to keep
        draining; a stalled HTTP call must not back up the firehose.
        """
        settings = self._settings
        try:
            rows = await asyncio.to_thread(
                fetch_trends, settings.trends_url, settings.trends_limit, int(time.time())
            )
            if rows:
                with self._db:
                    self._trends.upsert(rows)
        except Exception:  # noqa: BLE001 - an evaluation aid, never a blocker
            log.exception("trend poll failed; ingest continues")

    # ------------------------------------------------------------------- run

    async def run(self, stop: asyncio.Event) -> None:
        client = JetstreamClient(
            self._settings.jetstream_hosts,
            self._settings.collection,
            self._settings.max_cursor_age_seconds,
        )
        client.resume_from(self._meta.get(CURSOR_KEY))

        log.info("tracking %s topics: %s",
                 len(self._matcher.topic_names), ", ".join(self._matcher.topic_names))
        if self._settings.terms_enabled:
            log.info("term discovery on: top %s terms/minute",
                     self._settings.term_top_per_minute)

        settings = self._settings
        now = time.monotonic()
        last_flush = last_report = last_detect = last_prune = last_trends = now

        try:
            async for event in client.stream(stop):
                minute = event.timestamp - (event.timestamp % 60)
                self.posts_scanned += 1
                self._buffer.add_post(minute)

                for topic in self._matcher.match(event.text, event.lang):
                    self.matches_found += 1
                    self._buffer.add_match(minute, topic, event, settings.max_text_length)

                if settings.terms_enabled:
                    if minute != self._term_minute:
                        self._roll_terms(minute)
                    self._terms.add(extract_terms(event.text, event.tags), event.did)

                if self._sample_every and self.posts_scanned % self._sample_every == 0:
                    self._buffer.add_sample(event, settings.max_text_length)

                now = time.monotonic()
                if now - last_flush >= settings.flush_seconds:
                    self._flush(client.cursor)
                    last_flush = now
                if settings.detect_seconds > 0 and now - last_detect >= settings.detect_seconds:
                    self._detect()
                    last_detect = now
                if settings.prune_seconds > 0 and now - last_prune >= settings.prune_seconds:
                    self.prune()
                    last_prune = now
                if (
                    settings.trends_enabled
                    and settings.trends_seconds > 0
                    and now - last_trends >= settings.trends_seconds
                ):
                    await self._poll_trends()
                    last_trends = now
                if now - last_report >= REPORT_SECONDS:
                    log.info("scanned %s text posts | %s matches | %s term-minutes this run",
                             f"{self.posts_scanned:,}", f"{self.matches_found:,}",
                             f"{self.terms_written:,}")
                    last_report = now
        finally:
            self._roll_terms(None)
            self._flush(client.cursor)
            log.info("stopped after %s posts scanned, %s matches",
                     f"{self.posts_scanned:,}", f"{self.matches_found:,}")
