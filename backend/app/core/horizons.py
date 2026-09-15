"""Detection horizons: how soon an answer can arrive, and what it costs.

Warm-up is not a property of the algorithm. It is

    (window + gap + 1) * bucket_minutes

so the bucket size alone decides how long the collector must run before any
bucket can be scored. The original 15-minute bucket with a 32-bucket baseline
needed 8.75 hours before it would score its first window, and scored exactly
one when it got there. That is not a detector anyone can use.

A horizon is a point on that curve, not a better method. Shorter buckets start
sooner and shout more. Measured over a real 111-minute capture of 25 topics:

    bucket    warm-up    alerts/hour at z>=4    at z>=5
    1 min      33 min           25.8              19.7
    2 min      54 min           17.6              10.3
    4 min      60 min            9.2               3.5

Each horizon therefore carries its own z_threshold, chosen so its own alert
rate lands near a few per hour. `fast` is stricter than `deep` despite seeing
less history, because it takes far more shots: more buckets means more chances
to clear the bar by luck.

They are meant to run together, not to be chosen between. `fast` catches a
flash spike an hour into collection; `deep` has the long, stable baseline a
slow build needs before it looks like anything at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.detector import DetectionConfig


@dataclass(frozen=True)
class Horizon:
    name: str
    bucket_minutes: int
    window: int
    gap: int
    z_threshold: float
    min_hits: int
    description: str

    @property
    def warmup_minutes(self) -> int:
        """Collection time before the first bucket can be scored."""
        return (self.window + self.gap + 1) * self.bucket_minutes

    @property
    def warmup_hours(self) -> float:
        return round(self.warmup_minutes / 60, 2)

    def config(self, min_coverage: float) -> DetectionConfig:
        return DetectionConfig(
            window=self.window,
            gap=self.gap,
            z_threshold=self.z_threshold,
            min_hits=self.min_hits,
            min_coverage=min_coverage,
        )


HORIZONS: dict[str, Horizon] = {
    h.name: h
    for h in (
        Horizon(
            name="fast",
            bucket_minutes=4, window=12, gap=2,
            z_threshold=5.0, min_hits=5,
            description="Flash spikes. Usable one hour after collection starts.",
        ),
        Horizon(
            name="mid",
            bucket_minutes=8, window=27, gap=2,
            z_threshold=5.0, min_hits=5,
            description="Developing stories, over a four-hour baseline.",
        ),
        Horizon(
            name="deep",
            bucket_minutes=15, window=33, gap=2,
            z_threshold=4.0, min_hits=8,
            description="Slow builds. The steadiest baseline, nine hours in.",
        ),
    )
}

DEFAULT_HORIZON = "fast"


def get_horizon(name: str) -> Horizon:
    try:
        return HORIZONS[name]
    except KeyError:
        raise ValueError(
            f"unknown horizon {name!r}; expected one of {', '.join(HORIZONS)}"
        ) from None
