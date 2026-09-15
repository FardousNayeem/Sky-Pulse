#!/usr/bin/env python3
"""Fit the confidence model from collected history.

    python run_train.py            # build the dataset, fit, save
    python run_train.py --dry-run  # report what could be learned, change nothing

Every past spike becomes a training example once three buckets have passed
after it, because by then it is visible whether it held or reverted. No
external service and no waiting on anyone: the labels are already on disk.
"""
from __future__ import annotations

import argparse
import logging

from app.api.deps import get_connection
from app.config import get_settings
from app.db.repositories import (
    AlertsRepository,
    CountsRepository,
    MatchesRepository,
    SamplesRepository,
    TermsRepository,
)
from app.services.detection_service import DetectionService
from app.services.training_service import TrainingService

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="report the dataset without fitting or saving")
    args = parser.parse_args()

    settings = get_settings()
    db = get_connection()
    detection = DetectionService(
        CountsRepository(db), MatchesRepository(db), AlertsRepository(db),
        TermsRepository(db), SamplesRepository(db), settings,
    )
    trainer = TrainingService(detection, settings)

    if args.dry_run:
        rows, labels, _ = trainer.build_dataset()
        held = sum(labels)
        print(f"{len(rows)} labelled spikes: {held} held, {len(rows) - held} reverted")
        print(f"need {settings.model_min_samples} total and "
              f"{settings.model_min_positives} of each outcome to fit")
        return

    report = trainer.fit()
    if not report.trained:
        print(report.reason)
        return

    model = report.model
    holdout = (
        f"{model.holdout_auc} on {model.holdout_size} later spikes"
        if model.holdout_auc is not None
        else "not enough later history to measure"
    )
    print(f"trained on {model.trained_on} spikes ({model.positives} held)")
    print(f"in-sample accuracy {model.accuracy}, AUC {model.auc}")
    print(f"holdout AUC {holdout}")
    print(f"saved to {settings.model_path}")
    print("\nwhat it weighs most:")
    for name, weight in model.top_factors(8):
        direction = "higher -> more likely to hold" if weight > 0 else "higher -> more likely to revert"
        print(f"  {name:<22}{weight:>8.3f}   {direction}")


if __name__ == "__main__":
    main()
