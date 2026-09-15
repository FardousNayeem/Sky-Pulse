"""Data access. Every SQL statement in the project lives here."""
from __future__ import annotations

import sqlite3
import time
from collections import Counter, defaultdict

from app.core.detector import Bucket


class MetaRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: object) -> None:
        self._db.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


class CountsRepository:
    """Minute-level counters: the permanent, cheap part of the corpus."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def bulk_add(self, minute_totals: dict[int, int], topic_counts: dict[tuple[int, str], int]) -> None:
        if minute_totals:
            self._db.executemany(
                "INSERT INTO minute_totals(minute,posts) VALUES(?,?) "
                "ON CONFLICT(minute) DO UPDATE SET posts=posts+excluded.posts",
                list(minute_totals.items()),
            )
        if topic_counts:
            self._db.executemany(
                "INSERT INTO topic_minutes(minute,topic,hits) VALUES(?,?,?) "
                "ON CONFLICT(minute,topic) DO UPDATE SET hits=hits+excluded.hits",
                [(minute, topic, count) for (minute, topic), count in topic_counts.items()],
            )

    def bucket_frame(self, bucket_seconds: int) -> tuple[Counter, Counter]:
        """Per-bucket post totals and how many minutes of each were collected.

        The denominator and the coverage gate are the same for every subject in
        a pass - topics and discovered terms alike - so they are computed once
        and handed round rather than recounted per subject.
        """
        totals: Counter = Counter()
        coverage: Counter = Counter()
        for row in self._db.execute("SELECT minute, posts FROM minute_totals"):
            start = row["minute"] - (row["minute"] % bucket_seconds)
            totals[start] += row["posts"]
            coverage[start] += 1
        return totals, coverage

    def buckets_by_topic(self, bucket_seconds: int, topic: str | None = None) -> dict[str, list[Bucket]]:
        """Aggregate minutes into buckets, per topic, ordered by time."""
        totals, coverage = self.bucket_frame(bucket_seconds)

        query = "SELECT minute, topic, hits FROM topic_minutes"
        params: tuple = ()
        if topic:
            query += " WHERE topic=?"
            params = (topic,)

        per_topic: dict[str, Counter] = defaultdict(Counter)
        for row in self._db.execute(query, params):
            start = row["minute"] - (row["minute"] % bucket_seconds)
            per_topic[row["topic"]][start] += row["hits"]

        minutes_per_bucket = bucket_seconds / 60
        ordered_starts = sorted(totals)
        result: dict[str, list[Bucket]] = {}
        for name, counts in per_topic.items():
            result[name] = [
                Bucket(
                    start=start,
                    hits=counts.get(start, 0),
                    total=totals[start],
                    coverage=coverage[start] / minutes_per_bucket,
                )
                for start in ordered_starts
                if totals[start] > 0
            ]
        return result

    def series(self, topic: str, bucket_seconds: int, limit: int) -> list[Bucket]:
        buckets = self.buckets_by_topic(bucket_seconds, topic).get(topic, [])
        return buckets[-limit:]

    def summary(self) -> dict:
        row = self._db.execute(
            "SELECT MIN(minute) lo, MAX(minute) hi, SUM(posts) posts, COUNT(*) minutes "
            "FROM minute_totals"
        ).fetchone()
        return {
            "first_minute": row["lo"],
            "last_minute": row["hi"],
            "minutes_collected": row["minutes"] or 0,
            "posts_scanned": row["posts"] or 0,
        }

    def topic_totals(self) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT topic, SUM(hits) hits FROM topic_minutes GROUP BY topic"
        ).fetchall()
        return {row["topic"]: row["hits"] for row in rows}


class MatchesRepository:
    """Stored post text: a rolling window, for humans reading an alert."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def bulk_add(self, rows: list[tuple]) -> None:
        if rows:
            self._db.executemany(
                "INSERT INTO matches(ts,topic,did,rkey,lang,text,links) "
                "VALUES(?,?,?,?,?,?,?)", rows
            )

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]

    def in_window(self, topic: str, start: int, end: int, limit: int = 500) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT ts,did,rkey,lang,text,links FROM matches "
            "WHERE topic=? AND ts>=? AND ts<? ORDER BY ts LIMIT ?",
            (topic, start, end, limit),
        ).fetchall()

    def outside_window(
        self, topic: str, start: int, end: int, guard: int = 0, limit: int = 4000
    ) -> list[str]:
        """This topic's usual chatter, for contrast against a spike.

        Taken from before the spike, not from either side of it. An event that
        runs longer than one bucket spills into the buckets next to it, and
        contrasting a spike against its own overflow finds nothing distinctive
        - every word is equally common on both sides. `guard` widens the
        exclusion so the tail of the same event stays out of it.

        Before rather than after also matches how the score was computed: the
        baseline is a trailing window, so the explanation uses the same history
        the z-score did. Posts after the spike are the fallback for a spike
        near the start of collection, where there is no history yet.
        """
        rows = self._db.execute(
            "SELECT text FROM matches WHERE topic=? AND ts < ? ORDER BY ts DESC LIMIT ?",
            (topic, start - guard, limit),
        ).fetchall()
        if len(rows) < limit // 2:
            rows += self._db.execute(
                "SELECT text FROM matches WHERE topic=? AND ts >= ? ORDER BY ts LIMIT ?",
                (topic, end + guard, limit - len(rows)),
            ).fetchall()
        return [row["text"] for row in rows]

    def recent(self, topic: str, limit: int = 50) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT ts,did,rkey,lang,text,links FROM matches "
            "WHERE topic=? ORDER BY ts DESC LIMIT ?",
            (topic, limit),
        ).fetchall()

    def prune_before(self, cutoff_ts: int) -> int:
        cursor = self._db.execute("DELETE FROM matches WHERE ts < ?", (cutoff_ts,))
        return cursor.rowcount


class AlertsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def save_all(self, alerts: list[tuple]) -> int:
        """Persist a detection pass and commit it. Returns how many were new.

        One transaction for the whole pass, and an explicit one: sqlite3 opens
        an implicit transaction on the first write and never commits it by
        itself, so an INSERT outside a `with` block is visible to the process
        that wrote it and to nobody else - then rolled back when that process
        exits.

        Identity is (bucket, subject, mode, kind): one bucket can legitimately
        spike at more than one horizon, and a term can share a name with a
        topic without being the same finding.
        """
        if not alerts:
            return 0
        now = int(time.time())
        rows = [
            (
                spike.bucket_start, subject, kind, mode, spike.hits, spike.total,
                spike.share, spike.baseline, spike.zscore,
                ",".join(terms), " ".join(links), confidence, now,
            )
            for subject, kind, mode, spike, terms, links, confidence in alerts
        ]
        with self._db:
            cursor = self._db.executemany(
                "INSERT OR IGNORE INTO alerts"
                "(bucket,subject,kind,mode,hits,total,share,baseline,zscore,terms,links,"
                "confidence,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
        return cursor.rowcount

    def list(
        self,
        limit: int = 100,
        subject: str | None = None,
        mode: str | None = None,
        kind: str | None = None,
        sort: str = "recent",
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM alerts"
        where: list[str] = []
        params: list = []
        for column, value in (("subject", subject), ("mode", mode), ("kind", kind)):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if where:
            query += " WHERE " + " AND ".join(where)
        # Unscored alerts sort last under "confidence" rather than first: NULL
        # means no model has judged this one, which is not the same as judging
        # it likely.
        query += (
            " ORDER BY confidence IS NULL, confidence DESC, bucket DESC LIMIT ?"
            if sort == "confidence"
            else " ORDER BY bucket DESC, zscore DESC LIMIT ?"
        )
        params.append(limit)
        return self._db.execute(query, params).fetchall()

    def count(self, mode: str | None = None) -> int:
        if mode:
            return self._db.execute(
                "SELECT COUNT(*) c FROM alerts WHERE mode=?", (mode,)
            ).fetchone()["c"]
        return self._db.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]

    def counts_by_mode(self) -> dict[str, int]:
        return {
            r["mode"]: r["c"]
            for r in self._db.execute("SELECT mode, COUNT(*) c FROM alerts GROUP BY mode")
        }


class TermsRepository:
    """Minute-level counts for terms discovered in the stream itself."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def bulk_add(self, term_counts: dict[tuple[int, str], int]) -> None:
        if term_counts:
            self._db.executemany(
                "INSERT INTO term_minutes(minute,term,hits) VALUES(?,?,?) "
                "ON CONFLICT(minute,term) DO UPDATE SET hits=hits+excluded.hits",
                [(minute, term, hits) for (minute, term), hits in term_counts.items()],
            )

    def candidates(self, since: int, min_total_hits: int, limit: int) -> list[str]:
        """Terms worth scoring at all.

        Scoring every term ever seen would mean a baseline query per term per
        pass. Almost all of them appeared once and never again, so the list is
        cut to terms with enough total volume to clear `min_hits` in some
        bucket - which is the only way any of them could alert.
        """
        rows = self._db.execute(
            "SELECT term FROM term_minutes WHERE minute >= ? "
            "GROUP BY term HAVING SUM(hits) >= ? "
            "ORDER BY SUM(hits) DESC LIMIT ?",
            (since, min_total_hits, limit),
        ).fetchall()
        return [row["term"] for row in rows]

    def buckets_for(
        self, terms: list[str], bucket_seconds: int, totals: dict[int, int],
        coverage: dict[int, int], minutes_per_bucket: float,
    ) -> dict[str, list[Bucket]]:
        """Bucket series for each named term, sharing one pass over the table."""
        if not terms:
            return {}
        placeholders = ",".join("?" * len(terms))
        rows = self._db.execute(
            f"SELECT minute, term, hits FROM term_minutes WHERE term IN ({placeholders})",
            terms,
        ).fetchall()

        hits: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            start = row["minute"] - (row["minute"] % bucket_seconds)
            hits[row["term"]][start] += row["hits"]

        out: dict[str, list[Bucket]] = {}
        starts = sorted(totals)
        for term in terms:
            counted = hits.get(term, Counter())
            out[term] = [
                Bucket(
                    start=start,
                    hits=counted.get(start, 0),
                    total=totals[start],
                    coverage=coverage[start] / minutes_per_bucket,
                )
                for start in starts
                if totals[start] > 0
            ]
        return out

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) c FROM term_minutes").fetchone()["c"]

    def distinct_terms(self) -> int:
        return self._db.execute(
            "SELECT COUNT(DISTINCT term) c FROM term_minutes"
        ).fetchone()["c"]

    def prune_before(self, cutoff_minute: int) -> int:
        cursor = self._db.execute("DELETE FROM term_minutes WHERE minute < ?", (cutoff_minute,))
        return cursor.rowcount


class SamplesRepository:
    """A uniform sample of the stream, kept briefly to explain term spikes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def bulk_add(self, rows: list[tuple]) -> None:
        if rows:
            self._db.executemany(
                "INSERT INTO post_samples(ts,did,rkey,lang,text,links) VALUES(?,?,?,?,?,?)",
                rows,
            )

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) c FROM post_samples").fetchone()["c"]

    def ids_containing(self, term: str, start: int, end: int, limit: int = 400) -> set[str]:
        """Which sampled posts in a window mention the term.

        Identity is did/rkey rather than the row id so two terms counted from
        two queries agree about what "the same post" means.
        """
        return {
            f"{r['did']}/{r['rkey']}"
            for r in self.containing(term, start, end, limit)
        }

    def window(self, start: int, end: int, limit: int = 800) -> list[sqlite3.Row]:
        """Every sampled post in a window, for building a novelty background."""
        return self._db.execute(
            "SELECT ts,did,rkey,lang,text,links FROM post_samples "
            "WHERE ts>=? AND ts<? ORDER BY ts LIMIT ?",
            (start, end, limit),
        ).fetchall()

    def containing(self, term: str, start: int, end: int, limit: int = 400) -> list[sqlite3.Row]:
        """Sampled posts inside a window that mention the term.

        LIKE with a leading wildcard cannot use an index, but it only ever runs
        against one window of a short-retention table, so the scan is small.
        """
        return self._db.execute(
            "SELECT ts,did,rkey,lang,text,links FROM post_samples "
            "WHERE ts>=? AND ts<? AND lower(text) LIKE ? ORDER BY ts LIMIT ?",
            (start, end, f"%{term.lstrip('#').lower()}%", limit),
        ).fetchall()

    def outside(
        self, term: str, start: int, end: int, guard: int = 0, limit: int = 1500
    ) -> list[str]:
        """Sampled posts mentioning the term outside the spike and its guard band.

        Same reasoning as MatchesRepository.outside_window: a sustained event
        overflows into neighbouring buckets, and contrasting it against its own
        overflow yields nothing.
        """
        like = f"%{term.lstrip('#').lower()}%"
        rows = self._db.execute(
            "SELECT text FROM post_samples WHERE ts < ? AND lower(text) LIKE ? "
            "ORDER BY ts DESC LIMIT ?",
            (start - guard, like, limit),
        ).fetchall()
        if len(rows) < limit // 2:
            rows += self._db.execute(
                "SELECT text FROM post_samples WHERE ts >= ? AND lower(text) LIKE ? "
                "ORDER BY ts LIMIT ?",
                (end + guard, like, limit - len(rows)),
            ).fetchall()
        return [row["text"] for row in rows]

    def prune_before(self, cutoff_ts: int) -> int:
        cursor = self._db.execute("DELETE FROM post_samples WHERE ts < ?", (cutoff_ts,))
        return cursor.rowcount


class TrendsRepository:
    """Bluesky's own trending topics. Ground truth, polled for free."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def upsert(self, rows: list[tuple]) -> int:
        """Record what the platform is calling a trend right now.

        `first_seen` is never overwritten: the whole point is when a trend was
        first visible, so lead time can be measured against it.
        """
        if not rows:
            return 0
        cursor = self._db.executemany(
            "INSERT INTO bsky_trends"
            "(topic,display_name,description,category,status,post_count,started_at,"
            " first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(topic) DO UPDATE SET "
            "  display_name=excluded.display_name, description=excluded.description,"
            "  category=excluded.category, status=excluded.status,"
            "  post_count=excluded.post_count, last_seen=excluded.last_seen",
            rows,
        )
        return cursor.rowcount

    def list(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._db.execute(
            "SELECT * FROM bsky_trends ORDER BY first_seen DESC LIMIT ?", (limit,)
        ).fetchall()

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) c FROM bsky_trends").fetchone()["c"]


class EventsRepository:
    """Stories: clusters of terms that spiked together, chained over time."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection

    def upsert_all(self, events: list[dict]) -> int:
        """Write a pass of events and commit it.

        An event that is still running is updated rather than duplicated: its
        window extends, its peak and its story stay whichever were strongest.
        The first post in particular is never overwritten - it is the one fact
        about an event that cannot change once it is known.
        """
        if not events:
            return 0
        now = int(time.time())
        with self._db:
            for e in events:
                self._db.execute(
                    "INSERT INTO events(key,mode,terms,first_bucket,last_bucket,buckets,hits,"
                    "zscore,confidence,links,story_did,story_rkey,story_ts,story_text,"
                    "story_novelty,recurrence,recurs_from,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(key,mode) DO UPDATE SET"
                    "  terms=excluded.terms,"
                    "  last_bucket=MAX(last_bucket, excluded.last_bucket),"
                    "  first_bucket=MIN(first_bucket, excluded.first_bucket),"
                    "  buckets=excluded.buckets,"
                    "  hits=MAX(hits, excluded.hits),"
                    "  zscore=MAX(zscore, excluded.zscore),"
                    "  confidence=MAX(COALESCE(confidence,0), COALESCE(excluded.confidence,0)),"
                    "  links=excluded.links,"
                    "  story_did=COALESCE(story_did, excluded.story_did),"
                    "  story_rkey=COALESCE(story_rkey, excluded.story_rkey),"
                    "  story_ts=COALESCE(story_ts, excluded.story_ts),"
                    "  story_text=COALESCE(story_text, excluded.story_text),"
                    "  story_novelty=COALESCE(story_novelty, excluded.story_novelty),"
                    "  recurrence=excluded.recurrence,"
                    "  recurs_from=excluded.recurs_from",
                    (
                        e["key"], e["mode"], ",".join(e["terms"]), e["first_bucket"],
                        e["last_bucket"], e["buckets"], e["hits"], e["zscore"],
                        e.get("confidence"), " ".join(e.get("links", [])),
                        e.get("story_did"), e.get("story_rkey"), e.get("story_ts"),
                        e.get("story_text"), e.get("story_novelty"),
                        e.get("recurrence"), e.get("recurs_from"), now,
                    ),
                )
        return len(events)

    def list(self, limit: int = 100, mode: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM events"
        params: list = []
        if mode:
            query += " WHERE mode=?"
            params.append(mode)
        query += " ORDER BY last_bucket DESC, zscore DESC LIMIT ?"
        params.append(limit)
        return self._db.execute(query, params).fetchall()

    def get(self, key: str, mode: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM events WHERE key=? AND mode=?", (key, mode)
        ).fetchone()

    def before(self, mode: str, bucket: int, limit: int = 400) -> list[sqlite3.Row]:
        """Events that finished before a point in time, for recurrence checks."""
        return self._db.execute(
            "SELECT key, terms, first_bucket FROM events "
            "WHERE mode=? AND last_bucket < ? ORDER BY last_bucket DESC LIMIT ?",
            (mode, bucket, limit),
        ).fetchall()

    def open_since(self, mode: str, bucket: int, limit: int = 200) -> list[sqlite3.Row]:
        """Events still running, newest first, for chaining a new window onto."""
        return self._db.execute(
            "SELECT key, terms, last_bucket FROM events WHERE mode=? AND last_bucket >= ? "
            "ORDER BY last_bucket DESC LIMIT ?",
            (mode, bucket, limit),
        ).fetchall()

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
