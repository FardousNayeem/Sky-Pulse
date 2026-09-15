"""Horizon readiness, shared by the read and write sides.

Both `/api/stats` and `/api/detect` have to answer the same question - which
horizons can run yet - so the answer is built in one place rather than twice.
"""
from __future__ import annotations

from app.core.horizons import HORIZONS
from app.schemas import HorizonStatus


def horizon_statuses(minutes_collected: int, alerts_by_mode: dict[str, int]) -> list[HorizonStatus]:
    return [
        HorizonStatus(
            mode=h.name,
            description=h.description,
            bucket_minutes=h.bucket_minutes,
            baseline_window=h.window,
            z_threshold=h.z_threshold,
            min_hits=h.min_hits,
            warmup_minutes=h.warmup_minutes,
            warmup_hours=h.warmup_hours,
            ready=minutes_collected >= h.warmup_minutes,
            minutes_remaining=max(0, h.warmup_minutes - minutes_collected),
            alerts=alerts_by_mode.get(h.name, 0),
        )
        for h in HORIZONS.values()
    ]


def earliest_warmup_minutes() -> int:
    """The soonest any horizon becomes usable. Drives the 'still building' screen."""
    return min(h.warmup_minutes for h in HORIZONS.values())
