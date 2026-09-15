"""Fit the confidence model from history the collector already has.

The obstacle to learning anything here was never the algorithm, it was labels.
Bluesky's trending list supplies real ones, but only as it accumulates. There
is a second source available immediately, in data already on disk: whether a
spike *held*.

A real story stays elevated for a while. A blip is back to baseline in the next
bucket. That difference is visible in the buckets after any spike old enough to
have them, so every past spike is a labelled example the moment it is three
buckets old. It is a proxy - it learns what persists rather than what matters -
but it needs nobody's permission, it costs nothing, and it is the property that
decides whether an alert was worth showing a person.

When enough confirmed trends have accumulated, the same pipeline retrains
against those instead; only the label changes.
"""
from __future__ import annotations

import logging

from app.config import Settings
from app.core.detector import find_spikes, usable_buckets
from app.core.features import FEATURE_NAMES, persistence_label, spike_features
from app.core.horizons import HORIZONS
from app.core.logistic import LogisticModel, auc_score, train
from app.services.detection_service import TERM, TOPIC, DetectionService

log = logging.getLogger("pulse.training")

# Fraction of history used for fitting; the rest is the chronological holdout.
HOLDOUT_FROM = 0.7


class TrainingReport:
    def __init__(self, trained: bool, reason: str = "", model: LogisticModel | None = None):
        self.trained = trained
        self.reason = reason
        self.model = model


class TrainingService:
    def __init__(self, detection: DetectionService, settings: Settings) -> None:
        self._detection = detection
        self._settings = settings

    def build_dataset(self) -> tuple[list[list[float]], list[int], list[int]]:
        """Every past spike old enough to know how it turned out.

        Returns rows, labels and the bucket time of each, because the holdout
        split has to be chronological.
        """
        rows: list[list[float]] = []
        labels: list[int] = []
        times: list[int] = []
        kinds = [TOPIC] + ([TERM] if self._settings.terms_enabled else [])
        minutes = self._detection.minutes_collected()

        for horizon in HORIZONS.values():
            if minutes < horizon.warmup_minutes:
                continue
            config = horizon.config(self._settings.min_coverage)
            for kind in kinds:
                by_subject = self._detection.subject_buckets(horizon, None, kind)
                for subject, buckets in by_subject.items():
                    usable = usable_buckets(buckets, config)
                    position = {b.start: i for i, b in enumerate(usable)}
                    for spike in find_spikes(buckets, config):
                        index = position[spike.bucket_start]
                        label = persistence_label(spike, usable, index)
                        if label is None:
                            continue
                        end = spike.bucket_start + horizon.bucket_minutes * 60
                        terms, links = self._detection.explain(
                            kind, subject, spike.bucket_start, end,
                            horizon.bucket_minutes * 60,
                        )
                        rows.append(spike_features(
                            spike, usable, index, horizon.bucket_minutes,
                            kind, subject, terms, links,
                        ))
                        labels.append(label)
                        times.append(spike.bucket_start)
        return rows, labels, times

    def fit(self) -> TrainingReport:
        rows, labels, times = self.build_dataset()
        positives = sum(labels)
        floor = self._settings.model_min_samples
        min_positives = self._settings.model_min_positives

        if len(rows) < floor:
            return TrainingReport(False, (
                f"need {floor} labelled spikes to fit a model, have {len(rows)}. "
                "Keep collecting - every spike becomes a label once three buckets "
                "have passed after it."
            ))
        if positives < min_positives or len(rows) - positives < min_positives:
            return TrainingReport(False, (
                f"need at least {min_positives} of each outcome; have {positives} that "
                f"held and {len(rows) - positives} that reverted. A model fitted on "
                "one class predicts that class forever."
            ))

        # Chronological holdout, not a random one. Several spikes come from the
        # same event, so a random split puts siblings on both sides and the
        # score measures memorisation. Splitting on time also matches how the
        # model is actually used: fitted on the past, run on what comes next.
        order = sorted(range(len(rows)), key=lambda i: times[i])
        cut = int(len(order) * HOLDOUT_FROM)
        train_idx, test_idx = order[:cut], order[cut:]

        holdout_auc = None
        if len(test_idx) >= 30 and 0 < sum(labels[i] for i in test_idx) < len(test_idx):
            probe = train(
                [rows[i] for i in train_idx], [labels[i] for i in train_idx],
                FEATURE_NAMES, label_name="persistence",
            )
            holdout_auc = round(
                auc_score(
                    [labels[i] for i in test_idx],
                    [probe.predict(rows[i]) for i in test_idx],
                ),
                3,
            )

        # The shipped model is refitted on everything: the holdout existed to
        # produce an honest number, not to be thrown away.
        model = train(rows, labels, FEATURE_NAMES, label_name="persistence")
        model.holdout_auc = holdout_auc
        model.holdout_size = len(test_idx)
        model.save(self._settings.model_path)
        log.info("model trained on %s spikes (%s held), in-sample auc %s, holdout auc %s",
                 model.trained_on, model.positives, model.auc, model.holdout_auc)
        return TrainingReport(True, model=model)
