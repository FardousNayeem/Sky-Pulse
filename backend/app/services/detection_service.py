"""Write-side use case: run detection at one or more horizons, persist alerts.

Two kinds of subject are scored with the same arithmetic:

`topic` - a name from topics.json, matched by regex. Precise, and limited to
          what somebody thought to write down in advance.
`term`  - a word, bigram or hashtag taken from the stream itself. This is what
          makes the tool answer "what is happening" rather than "is anything
          happening to these 26 things".

A horizon is a bucket size and the amount of history behind it. Because warm-up
is (window + gap + 1) * bucket_minutes, the choice of bucket decides how soon
anything can be scored at all. Scoring is retroactive over everything already
in SQLite, so a horizon that becomes available late still scores the whole
history the moment it runs.
"""
from __future__ import annotations

import logging

from app.config import Settings
from app.core.detector import find_spikes, usable_buckets
from app.core.features import spike_features
from app.core.horizons import HORIZONS, Horizon, get_horizon
from app.core.logistic import LogisticModel
from app.core.novelty import distinctive_terms, top_links
from app.db.repositories import (
    AlertsRepository,
    CountsRepository,
    MatchesRepository,
    SamplesRepository,
    TermsRepository,
)
from app.schemas import Alert, DetectionRun, HorizonStatus
from app.services.horizon_service import horizon_statuses

log = logging.getLogger("pulse.detection")

TOPIC, TERM = "topic", "term"

# A term has to clear min_hits in a single bucket to alert at all, so anything
# whose entire history is a small multiple of that cannot possibly qualify.
# Filtering on it first keeps the candidate list to the terms worth scoring.
CANDIDATE_HITS_MULTIPLE = 4

# Buckets excluded either side of a spike when gathering its contrast set. An
# event rarely fits one bucket exactly, and its overflow is not "usual chatter".
CONTRAST_GUARD_BUCKETS = 3


class DetectionService:
    def __init__(
        self,
        counts: CountsRepository,
        matches: MatchesRepository,
        alerts: AlertsRepository,
        terms: TermsRepository,
        samples: SamplesRepository,
        settings: Settings,
    ) -> None:
        self._counts = counts
        self._matches = matches
        self._alerts = alerts
        self._terms = terms
        self._samples = samples
        self._settings = settings

    # ----------------------------------------------------------------- model

    def _model(self) -> LogisticModel | None:
        """The confidence model, reloaded when the file changes.

        Cached on mtime rather than forever: the collector is a long-running
        process, and retraining should take effect without restarting ingest.
        """
        path = self._settings.model_path
        try:
            stamp = path.stat().st_mtime
        except OSError:
            self._cached_model = None
            self._cached_stamp = None
            return None
        if stamp != getattr(self, "_cached_stamp", None):
            self._cached_model = LogisticModel.load(path)
            self._cached_stamp = stamp
        return self._cached_model

    def model_info(self) -> dict | None:
        model = self._model()
        if model is None:
            return None
        info = model.to_dict()
        info.pop("mean", None)
        info.pop("std", None)
        info["top_factors"] = model.top_factors()
        return info

    # ---------------------------------------------------------------- status

    def minutes_collected(self) -> int:
        return self._counts.summary()["minutes_collected"]

    def horizons(self) -> list[HorizonStatus]:
        """Every horizon, whether it can run yet, and how long until it can."""
        return horizon_statuses(self.minutes_collected(), self._alerts.counts_by_mode())

    # ------------------------------------------------------------- detection

    def run(self, mode: str, subject: str | None = None, kind: str | None = None) -> DetectionRun:
        """Score one horizon. Defaults to topics, the cheaper of the two kinds."""
        return self._run(get_horizon(mode), subject, kind or TOPIC)

    def run_all(self, subject: str | None = None) -> list[DetectionRun]:
        """Score every horizon, both kinds. Horizons still warming up cost nothing."""
        kinds = [TOPIC] + ([TERM] if self._settings.terms_enabled else [])
        return [self._run(h, subject, kind) for h in HORIZONS.values() for kind in kinds]

    def _run(self, horizon: Horizon, subject: str | None, kind: str) -> DetectionRun:
        minutes = self.minutes_collected()
        if minutes < horizon.warmup_minutes:
            return DetectionRun(
                ran=False,
                mode=horizon.name,
                kind=kind,
                reason=(
                    f"'{horizon.name}' needs {horizon.warmup_minutes} minutes of collection "
                    f"({horizon.warmup_hours}h) for its {horizon.bucket_minutes}-minute buckets; "
                    f"have {minutes}. {horizon.warmup_minutes - minutes} to go"
                ),
                bucket_minutes=horizon.bucket_minutes,
                z_threshold=horizon.z_threshold,
                minutes_remaining=horizon.warmup_minutes - minutes,
            )

        by_subject = self.subject_buckets(horizon, subject, kind)
        config = horizon.config(self._settings.min_coverage)
        model = self._model()
        pending: list[tuple] = []

        for name, buckets in by_subject.items():
            usable = usable_buckets(buckets, config) if model else []
            position = {b.start: i for i, b in enumerate(usable)}
            for spike in find_spikes(buckets, config):
                end = spike.bucket_start + horizon.bucket_minutes * 60
                terms, links = self.explain(
                    kind, name, spike.bucket_start, end, horizon.bucket_minutes * 60
                )
                confidence = None
                if model:
                    confidence = model.predict(spike_features(
                        spike, usable, position[spike.bucket_start],
                        horizon.bucket_minutes, kind, name, terms, links,
                    ))
                pending.append((name, kind, horizon.name, spike, terms, links, confidence))

        found = len(pending)
        new = self._alerts.save_all(pending)

        if new:
            log.info("%s/%s: %s new alerts", horizon.name, kind, new)
        return DetectionRun(
            ran=True,
            mode=horizon.name,
            kind=kind,
            alerts_found=found,
            new_alerts=new,
            topics_scanned=len(by_subject),
            bucket_minutes=horizon.bucket_minutes,
            z_threshold=horizon.z_threshold,
        )

    # --------------------------------------------------------------- sources

    def subject_buckets(self, horizon: Horizon, subject: str | None, kind: str) -> dict:
        """Bucket series per subject, for whichever kind is being scored."""
        if kind == TOPIC:
            return self._counts.buckets_by_topic(horizon.bucket_minutes * 60, subject)
        return self._term_buckets(horizon, subject)

    def _term_buckets(self, horizon: Horizon, subject: str | None) -> dict:
        bucket_seconds = horizon.bucket_minutes * 60
        totals, coverage = self._counts.bucket_frame(bucket_seconds)
        if not totals:
            return {}

        if subject:
            candidates = [subject]
        else:
            candidates = self._terms.candidates(
                since=min(totals),
                min_total_hits=horizon.min_hits * CANDIDATE_HITS_MULTIPLE,
                limit=self._settings.term_candidate_limit,
            )
        return self._terms.buckets_for(
            candidates, bucket_seconds, totals, coverage, horizon.bucket_minutes
        )

    def explain(
        self, kind: str, name: str, start: int, end: int, bucket_seconds: int
    ) -> tuple[list[str], list[str]]:
        """What made this window different, and what people were linking to.

        The guard band keeps the buckets immediately around the spike out of
        the contrast set, for the same reason the detector skips them when
        building a baseline: a developing event is already in them.
        """
        guard = bucket_seconds * CONTRAST_GUARD_BUCKETS
        if kind == TOPIC:
            rows = self._matches.in_window(name, start, end)
            outside = self._matches.outside_window(name, start, end, guard)
        else:
            rows = self._samples.containing(name, start, end)
            outside = self._samples.outside(name, start, end, guard)

        inside = [row["text"] for row in rows]
        terms = [t for t in distinctive_terms(inside, outside) if t != name]
        return terms, top_links([row["links"] for row in rows])

    # ----------------------------------------------------------------- reads

    def list_alerts(
        self,
        limit: int = 100,
        subject: str | None = None,
        mode: str | None = None,
        kind: str | None = None,
        sort: str = "recent",
    ) -> list[Alert]:
        if sort not in ("recent", "confidence"):
            raise ValueError(f"unknown sort {sort!r}; expected recent or confidence")
        if mode is not None:
            get_horizon(mode)  # reject an unknown mode rather than return nothing
        if kind is not None and kind not in (TOPIC, TERM):
            raise ValueError(f"unknown kind {kind!r}; expected {TOPIC} or {TERM}")

        out = []
        for r in self._alerts.list(limit, subject, mode, kind, sort):
            baseline = r["baseline"]
            out.append(
                Alert(
                    id=r["id"], subject=r["subject"], kind=r["kind"], mode=r["mode"],
                    bucket=r["bucket"], hits=r["hits"], total=r["total"], share=r["share"],
                    baseline=baseline, zscore=r["zscore"],
                    multiple=(r["share"] / baseline) if baseline > 0 else 0.0,
                    terms=[t for t in (r["terms"] or "").split(",") if t],
                    links=[u for u in (r["links"] or "").split() if u],
                    confidence=r["confidence"],
                    created_at=r["created_at"],
                )
            )
        return out
