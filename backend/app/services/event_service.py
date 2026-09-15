"""Turn term alerts into stories.

Three things happen here, and they only make sense together:

1. **Cluster.** Terms that spiked in the same window and appear in the same
   posts are one story said three ways, not three findings.
2. **Find the first telling.** Within the story's posts, the earliest one that
   does not resemble anything already being said is where it started.
3. **Check whether it has happened before.** A show that airs nightly trends
   nightly. The second time is not news, and saying so is the difference
   between a feed worth reading and one worth muting.

Only discovered terms are clustered. Watchlist topics are matched by regex
against phrases that need not appear in the topic's own name, so the sampled
corpus cannot be asked which posts belong to them without a second, different
join - and a wrong join here would invent relationships rather than find them.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from app.config import Settings
from app.core.events import chain, cluster_terms, event_key, jaccard
from app.core.horizons import get_horizon
from app.core.lsh import first_story
from app.db.repositories import AlertsRepository, EventsRepository, SamplesRepository
from app.schemas import Event

log = logging.getLogger("pulse.events")

# How much of an earlier event's wording a new one must share before it counts
# as the same thing happening again.
RECURRENCE_SIMILARITY = 0.6

# An event cannot recur against itself an hour ago; a repeat means a different
# occasion, so only events that finished a good while back are compared.
RECURRENCE_MIN_AGE_SECONDS = 20 * 3600

# Background for novelty: the window immediately before the spike. Long enough
# that an ordinary mention of the subject is in it, short enough to stay cheap.
BACKGROUND_BUCKETS = 6

# How stale an event may be and still absorb a new window. Beyond this it has
# ended, and the same wording appearing again is a repeat rather than the same
# story still running - which is the whole distinction recurrence rests on.
CHAIN_MAX_GAP_BUCKETS = 3


class EventService:
    def __init__(
        self,
        alerts: AlertsRepository,
        events: EventsRepository,
        samples: SamplesRepository,
        settings: Settings,
    ) -> None:
        self._alerts = alerts
        self._events = events
        self._samples = samples
        self._settings = settings

    # ------------------------------------------------------------------ read

    def list_events(self, limit: int = 100, mode: str | None = None) -> list[Event]:
        return [self._to_schema(r) for r in self._events.list(limit, mode)]

    def get_event(self, key: str, mode: str) -> Event | None:
        row = self._events.get(key, mode)
        return self._to_schema(row) if row else None

    @staticmethod
    def _to_schema(r) -> Event:
        return Event(
            key=r["key"], mode=r["mode"],
            terms=[t for t in r["terms"].split(",") if t],
            first_bucket=r["first_bucket"], last_bucket=r["last_bucket"],
            buckets=r["buckets"], hits=r["hits"], zscore=r["zscore"],
            confidence=r["confidence"],
            links=[u for u in (r["links"] or "").split() if u],
            story_did=r["story_did"], story_rkey=r["story_rkey"],
            story_ts=r["story_ts"], story_text=r["story_text"],
            story_novelty=r["story_novelty"],
            story_url=(
                f"https://bsky.app/profile/{r['story_did']}/post/{r['story_rkey']}"
                if r["story_did"] and r["story_rkey"] else None
            ),
            recurrence=r["recurrence"], recurs_from=r["recurs_from"],
        )

    # ----------------------------------------------------------------- build

    def rebuild(self, mode: str, limit: int = 2000) -> int:
        """Group this horizon's term alerts into events. Returns events written."""
        horizon = get_horizon(mode)
        width = horizon.bucket_minutes * 60

        by_bucket: dict[int, list] = defaultdict(list)
        for alert in self._alerts.list(limit=limit, mode=mode, kind="term"):
            by_bucket[alert["bucket"]].append(alert)
        if not by_bucket:
            return 0

        written: list[dict] = []
        # Chaining state is carried across buckets rather than re-read per
        # bucket: nothing is on disk until the pass commits, so an event that
        # started two buckets ago is only visible here.
        open_events: list[tuple[str, set[str], int]] = [
            (r["key"], {t for t in r["terms"].split(",") if t}, r["last_bucket"])
            for r in self._events.open_since(
                mode, min(by_bucket) - width * CHAIN_MAX_GAP_BUCKETS
            )
        ]
        spans: dict[str, dict] = {}

        # Oldest first: an event can only continue one that already exists, and
        # its first telling is only first if nothing earlier has been indexed.
        for bucket in sorted(by_bucket):
            for event in self._bucket_events(
                mode, bucket, width, by_bucket[bucket], open_events, spans
            ):
                self._extend(spans, event)
        written = list(spans.values())

        count = self._events.upsert_all(written)
        if count:
            log.info("%s: %s event(s)", mode, count)
        return count

    def rebuild_all(self) -> int:
        from app.core.horizons import HORIZONS
        return sum(self.rebuild(name) for name in HORIZONS)

    @staticmethod
    def _extend(spans: dict[str, dict], event: dict) -> None:
        """Fold a window's finding into the event it belongs to.

        An event seen in four consecutive buckets is one event four buckets
        long, not four events. The peak survives, the window widens, and the
        first telling is kept from whichever window actually found it.
        """
        existing = spans.get(event["key"])
        if existing is None:
            spans[event["key"]] = event
            return
        existing["last_bucket"] = max(existing["last_bucket"], event["last_bucket"])
        existing["first_bucket"] = min(existing["first_bucket"], event["first_bucket"])
        existing["buckets"] += 1
        existing["hits"] = max(existing["hits"], event["hits"])
        existing["terms"] = sorted(set(existing["terms"]) | set(event["terms"]))
        if event["zscore"] > existing["zscore"]:
            existing["zscore"] = event["zscore"]
        if event.get("confidence") is not None:
            existing["confidence"] = max(existing.get("confidence") or 0.0, event["confidence"])
        for url in event.get("links", []):
            if url not in existing["links"]:
                existing["links"].append(url)
        if not existing.get("story_rkey") and event.get("story_rkey"):
            for field in ("story_did", "story_rkey", "story_ts", "story_text", "story_novelty"):
                existing[field] = event.get(field)

    def _bucket_events(
        self, mode: str, bucket: int, width: int, alerts: list,
        open_events: list[tuple[str, set[str], int]],
        spans: dict[str, dict],
    ) -> list[dict]:
        end = bucket + width
        by_subject = {a["subject"]: a for a in alerts}
        term_posts = {
            subject: self._samples.ids_containing(subject, bucket, end)
            for subject in by_subject
        }
        # Events old enough to be a previous occasion, from disk and from
        # earlier in this same pass. The pass has committed nothing yet, so
        # without the second source a rebuild over several days would never see
        # its own first day and no repeat would ever be recognised.
        age_cutoff = bucket - RECURRENCE_MIN_AGE_SECONDS
        past = [
            (r["key"], {t for t in r["terms"].split(",") if t})
            for r in self._events.before(mode, age_cutoff)
        ] + [
            (key, set(e["terms"]))
            for key, e in spans.items()
            if e["last_bucket"] < age_cutoff
        ]

        # Only events still running can be continued. Without this an event
        # never ends, and a story that runs again next week is glued onto the
        # one from last week instead of being recognised as a repeat.
        cutoff = bucket - width * CHAIN_MAX_GAP_BUCKETS
        live = [(key, terms) for key, terms, last in open_events if last >= cutoff]

        out = []
        for cluster in cluster_terms(term_posts):
            members = [by_subject[t] for t in cluster]
            key = chain(cluster, live) or event_key(cluster, bucket)
            peak = max(members, key=lambda a: a["zscore"])

            event = {
                "key": key,
                "mode": mode,
                "terms": sorted(cluster),
                "first_bucket": bucket,
                "last_bucket": bucket,
                "buckets": 1,
                "hits": sum(a["hits"] for a in members),
                "zscore": peak["zscore"],
                "confidence": max(
                    (a["confidence"] for a in members if a["confidence"] is not None),
                    default=None,
                ),
                "links": self._merge_links(members),
            }
            event.update(self._story(cluster, bucket, end, width))
            event.update(self._recurrence(cluster, past))
            out.append(event)
            live.insert(0, (key, set(cluster)))
            open_events.insert(0, (key, set(cluster), bucket))
        return out

    @staticmethod
    def _merge_links(members: list) -> list[str]:
        seen: list[str] = []
        for a in members:
            for url in (a["links"] or "").split():
                if url not in seen:
                    seen.append(url)
        return seen[:3]

    def _story(self, cluster: set[str], bucket: int, end: int, width: int) -> dict:
        """The post that said it first, against what was being said before."""
        candidates: dict[str, tuple] = {}
        for term in cluster:
            for r in self._samples.containing(term, bucket, end):
                candidates[f"{r['did']}/{r['rkey']}"] = (r["ts"], r["did"], r["rkey"], r["text"])
        if not candidates:
            return {}

        background = [
            r["text"]
            for r in self._samples.window(bucket - width * BACKGROUND_BUCKETS, bucket)
        ]
        found = first_story(list(candidates.values()), background)
        if found:
            (ts, did, rkey, text), novelty = found
        else:
            # Everything in the window resembled something already being said,
            # so this spike is a continuation rather than a beginning. The
            # earliest post is still the right thing to show; the novelty score
            # records that it was not actually new.
            ts, did, rkey, text = min(candidates.values(), key=lambda c: c[0])
            novelty = 0.0
        return {
            "story_did": did, "story_rkey": rkey, "story_ts": ts,
            "story_text": text[:400], "story_novelty": novelty,
        }

    @staticmethod
    def _recurrence(cluster: set[str], past: list[tuple[str, set[str]]]) -> dict:
        """Whether this story has run before, and how closely."""
        best_key, best_score = None, 0.0
        for key, terms in past:
            score = jaccard(cluster, terms)
            if score > best_score:
                best_key, best_score = key, score
        if best_score >= RECURRENCE_SIMILARITY:
            return {"recurrence": round(best_score, 3), "recurs_from": best_key}
        return {"recurrence": round(best_score, 3) if best_key else None, "recurs_from": None}
