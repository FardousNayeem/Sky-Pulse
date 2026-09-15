#!/usr/bin/env python3
"""Score already-collected history. No network, no streaming.

    python run_detect.py               # every horizon and kind that is ready
    python run_detect.py --mode fast   # just one horizon
    python run_detect.py --kind term   # only terms found in the stream
    python run_detect.py --list        # what each horizon needs, and has

Detection is retroactive: it reads buckets out of SQLite and scores all of
them, so history collected before any of this existed is scored the first time
this runs. A database that has nine hours in it gets nine hours of answers.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.core.horizons import HORIZONS
from app.db.database import create_connection
from app.db.repositories import (
    AlertsRepository,
    CountsRepository,
    MatchesRepository,
    SamplesRepository,
    TermsRepository,
)
from app.services.detection_service import DetectionService

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def _clock(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%m-%d %H:%M")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(HORIZONS), help="score one horizon only")
    parser.add_argument("--kind", choices=("topic", "term"), help="score one kind only")
    parser.add_argument("--subject", help="score one topic or term only")
    parser.add_argument("--list", action="store_true", help="show horizon readiness and exit")
    parser.add_argument("--show", type=int, default=20, help="how many alerts to print")
    parser.add_argument("--sort", choices=("recent", "confidence"), default="recent",
                        help="order alerts by recency or by learned confidence")
    args = parser.parse_args()

    settings = get_settings()
    db = create_connection(settings.database_path)
    service = DetectionService(
        CountsRepository(db), MatchesRepository(db), AlertsRepository(db),
        TermsRepository(db), SamplesRepository(db), settings,
    )

    minutes = service.minutes_collected()
    print(f"{minutes} minutes collected ({minutes / 60:.2f}h)\n")

    print(f"{'horizon':<8}{'bucket':>8}{'warm-up':>10}{'z':>6}{'status':>16}{'alerts':>8}")
    for h in service.horizons():
        status = "ready" if h.ready else f"{h.minutes_remaining} min to go"
        print(f"{h.mode:<8}{str(h.bucket_minutes) + 'm':>8}{str(h.warmup_hours) + 'h':>10}"
              f"{h.z_threshold:>6}{status:>16}{h.alerts:>8}")
    if args.list:
        return

    print()
    if args.mode:
        runs = [service.run(args.mode, args.subject, args.kind)]
    else:
        runs = [r for r in service.run_all(args.subject) if not args.kind or r.kind == args.kind]
    for run in runs:
        label = f"{run.mode}/{run.kind}"
        if run.ran:
            print(f"{label}: scored {run.topics_scanned} subject(s), "
                  f"{run.alerts_found} spike(s), {run.new_alerts} new")
        else:
            print(f"{label}: {run.reason}")

    alerts = service.list_alerts(
        limit=args.show, subject=args.subject, mode=args.mode, kind=args.kind, sort=args.sort
    )
    if not alerts:
        print("\nNo alerts.")
        return

    info = service.model_info()
    if info:
        print(f"\nconfidence model: {info['trained_on']} spikes, "
              f"holdout AUC {info['holdout_auc']}")
    else:
        print("\nno confidence model yet - run `python run_train.py`")

    print(f"\n{'when':<13}{'conf':>5}  {'mode':<6}{'kind':<6}{'subject':<22}{'hits':>6}{'z':>7}"
          f"{'vs base':>9}  why")
    for a in alerts:
        multiple = f"{a.multiple:.1f}x" if a.multiple else "new"
        why = ", ".join(a.terms[:4])
        if a.links:
            why = f"{why}  {a.links[0]}" if why else a.links[0]
        conf = f"{a.confidence:.2f}" if a.confidence is not None else "  -  "
        print(f"{_clock(a.bucket):<13}{conf:>5}  {a.mode:<6}{a.kind:<6}{a.subject[:21]:<22}"
              f"{a.hits:>6}{a.zscore:>7.1f}{multiple:>9}  {why}")


if __name__ == "__main__":
    main()
