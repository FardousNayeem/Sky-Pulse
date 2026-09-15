"""Measure this detector against Bluesky's own trending list.

Without this there is no answer to the only question that matters - is any of
this real - and no way to tune a threshold except by taste. Bluesky publishes
what it considers trending, free and unauthenticated, which makes it both the
competitor and the label set.

The useful number is not coverage but **lead time**: the platform's list is
curated and slow, so a detector reading the same firehose ought to see a story
first. Minutes ahead is a claim that can be checked; "found a trend" is not.
"""
from __future__ import annotations

from statistics import median

from app.core.novelty import STOPWORDS
from app.core.terms import words
from app.db.repositories import AlertsRepository, TrendsRepository
from app.schemas import BenchmarkReport, TrendMatch

# Two independent terms agreeing is evidence; one is a coincidence waiting to
# happen, since a single common word appears in many unrelated trends.
MIN_TERM_OVERLAP = 2

# A one-word subject is weak evidence on its own. Measured against a real
# trending list, the single word "users" matched three unrelated headlines -
# it appears in the description of anything phrased "Users joked that...".
# A multi-word subject ("lady gaga") or a hashtag is specific enough to stand
# alone; a bare word has to be corroborated by one of the spike's own terms.
MIN_SUPPORT_FOR_SINGLE_WORD = 1

# An alert from last week did not predict today's trend. Matches are confined
# to a window around the moment the platform first listed it, so lead time
# measures detection rather than coincidence over a long archive.
MAX_LEAD_SECONDS = 24 * 3600
MAX_LAG_SECONDS = 6 * 3600


def _tokens(text: str) -> set[str]:
    """Content words and adjacent pairs of a trend headline."""
    tokens = words(text)
    out = {w for w in tokens if len(w) >= 3 and w not in STOPWORDS}
    out.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return out


class BenchmarkService:
    def __init__(self, alerts: AlertsRepository, trends: TrendsRepository) -> None:
        self._alerts = alerts
        self._trends = trends

    def report(self, limit: int = 100) -> BenchmarkReport:
        trends = self._trends.list(limit)
        # Oldest first, so the first alert that matches a trend is the earliest
        # one - that is the lead time, not merely a lead time.
        alerts = sorted(self._alerts.list(limit=2000), key=lambda r: r["bucket"])

        rows = [self._match(trend, alerts) for trend in trends]
        leads = [r.lead_minutes for r in rows if r.lead_minutes is not None]
        matched = sum(1 for r in rows if r.matched)

        return BenchmarkReport(
            trends_tracked=len(rows),
            matched=matched,
            coverage=round(matched / len(rows), 3) if rows else 0.0,
            median_lead_minutes=round(median(leads), 1) if leads else None,
            best_lead_minutes=max(leads) if leads else None,
            rows=rows,
        )

    def _match(self, trend, alerts) -> TrendMatch:
        wanted = _tokens(f"{trend['display_name']} {trend['description']}")
        first_seen = trend["first_seen"]

        for alert in alerts:
            if not -MAX_LAG_SECONDS <= first_seen - alert["bucket"] <= MAX_LEAD_SECONDS:
                continue

            raw = alert["subject"].lower()
            subject = raw.lstrip("#")
            terms = {t.lstrip("#").lower() for t in (alert["terms"] or "").split(",") if t}
            overlap = len(terms & wanted)
            specific = " " in subject or raw.startswith("#")

            basis = ""
            if subject in wanted and (specific or overlap >= MIN_SUPPORT_FOR_SINGLE_WORD):
                basis = "subject"
            elif overlap >= MIN_TERM_OVERLAP:
                basis = "terms"
            if not basis:
                continue

            return TrendMatch(
                topic=trend["topic"], display_name=trend["display_name"],
                category=trend["category"], status=trend["status"],
                post_count=trend["post_count"], first_seen=first_seen,
                matched=True, match_basis=basis,
                alert_id=alert["id"], alert_subject=alert["subject"],
                alert_kind=alert["kind"], alert_mode=alert["mode"],
                alert_bucket=alert["bucket"],
                lead_minutes=round((first_seen - alert["bucket"]) / 60),
            )

        return TrendMatch(
            topic=trend["topic"], display_name=trend["display_name"],
            category=trend["category"], status=trend["status"],
            post_count=trend["post_count"], first_seen=first_seen, matched=False,
        )
