"""Spike detection. Pure functions over plain numbers - no I/O.

Method
------
Score a topic's SHARE of conversation (hits / all text posts), not its raw
count: when the whole network gets busy every topic's raw count rises, but its
share does not.

Baseline is the median of a trailing window, with a gap of buckets skipped
immediately before the bucket under test so a developing spike does not sit in
its own baseline. Spread is MAD rather than standard deviation, so one past
spike does not permanently raise the bar.

An alert requires both a high z-score and a meaningful absolute count, so a
2 -> 6 blip on a quiet topic never pages anyone.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median

MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Bucket:
    """One time window of observations for a single topic."""
    start: int      # unix seconds, bucket start
    hits: int       # posts matching this topic
    total: int      # all text-bearing posts seen in the window
    coverage: float # fraction of the window the collector was actually running

    @property
    def share(self) -> float:
        return self.hits / self.total if self.total else 0.0


@dataclass(frozen=True)
class Spike:
    bucket_start: int
    hits: int
    total: int
    share: float
    baseline: float
    zscore: float
    coverage: float

    @property
    def multiple(self) -> float:
        return self.share / self.baseline if self.baseline > 0 else float("inf")


DAY_SECONDS = 86_400


@dataclass(frozen=True)
class DetectionConfig:
    window: int = 32          # trailing buckets forming the baseline
    gap: int = 2              # buckets skipped between baseline and test bucket
    z_threshold: float = 4.0
    min_hits: int = 8
    min_coverage: float = 0.8
    # Same clock time on previous days, added to the baseline when enough of
    # them exist. Scoring share rather than count already removes the network's
    # own daily rhythm, because the denominator carries it - but it cannot
    # remove a rhythm belonging to one subject, like a league that plays at
    # eight every evening. That needs the subject's own history at this hour.
    seasonal_days: int = 7
    seasonal_min_samples: int = 3

    @property
    def min_buckets(self) -> int:
        return self.window + self.gap + 1


def _counting_noise(center: float, total: int) -> float:
    """The smallest share difference a window can actually resolve.

    Hits arrive Poisson, so a share p measured over `total` posts carries a
    standard error of sqrt(p / total). A baseline of exactly zero still has a
    floor, because one post is the finest share the window can express.
    """
    if total <= 0:
        return 1e-9
    return sqrt(max(center, 1.0 / total) / total)


def _robust_sigma(values: list[float], center: float, total: int) -> float:
    """MAD spread, floored by counting noise.

    MAD is zero whenever most baseline buckets hold the same count, which for a
    sparse topic is routine and usually means they all hold none. Dividing by a
    1e-9 epsilon there produced z-scores in the hundreds of thousands and
    ranked the quietest topics above every real spike. The Poisson floor is the
    honest replacement: it is what the spread must be at that count, not an
    arbitrary small number.
    """
    mad = median([abs(v - center) for v in values])
    return max(MAD_TO_SIGMA * mad, _counting_noise(center, total))


def _bucket_seconds(buckets: list[Bucket]) -> int:
    """Spacing between buckets, inferred rather than passed in.

    The scorer is handed a series, not a configuration, and every caller
    already spaced it evenly; asking for the width again would be one more
    thing that can disagree with the data.
    """
    return buckets[1].start - buckets[0].start if len(buckets) > 1 else 0


def _seasonal_samples(
    by_start: dict[int, float], start: int, config: DetectionConfig
) -> list[float]:
    """This subject's share at the same clock time on previous days.

    Returned only when enough of those days were actually collected. Below
    that the sample is too small to be a baseline and adding it would just
    make the median noisier, so detection behaves exactly as it did before -
    which is also what happens for the first week of any deployment.
    """
    samples = [
        by_start[start - day * DAY_SECONDS]
        for day in range(1, config.seasonal_days + 1)
        if start - day * DAY_SECONDS in by_start
    ]
    return samples if len(samples) >= config.seasonal_min_samples else []


def _baseline(trailing: list[float], seasonal: list[float]) -> tuple[list[float], float]:
    """Normal for this bucket: the higher of two readings of it.

    The trailing window answers "unusual compared with the last hour". The
    seasonal set answers "unusual compared with this hour on other days". A
    subject with a rhythm - a league that plays every evening, a show that airs
    nightly - clears the first easily and the second not at all.

    Taking the larger of the two means a spike has to beat both. It can only
    raise the bar, never lower it, so adding seasonal history removes false
    positives without costing a detection. The spread is read from whichever
    set supplied the level, so scale and level describe the same thing.
    """
    trailing_center = median(trailing)
    if not seasonal:
        return trailing, trailing_center

    seasonal_center = median(seasonal)
    if seasonal_center > trailing_center:
        return seasonal, seasonal_center
    return trailing, trailing_center


def usable_buckets(buckets: list[Bucket], config: DetectionConfig) -> list[Bucket]:
    """Buckets the collector actually covered.

    Exposed because anything reasoning about a spike's position in the series -
    features, labels - has to index the same list the scorer did, or it is
    describing a different bucket.
    """
    return [b for b in buckets if b.coverage >= config.min_coverage]


def find_spikes(buckets: list[Bucket], config: DetectionConfig) -> list[Spike]:
    """Score each bucket against its own trailing baseline."""
    usable = usable_buckets(buckets, config)
    shares = [b.share for b in usable]
    spikes: list[Spike] = []

    by_start = {b.start: b.share for b in usable}
    bucket_seconds = _bucket_seconds(usable)

    for i, bucket in enumerate(usable):
        lo = i - config.gap - config.window
        hi = i - config.gap
        if lo < 0 or hi <= lo:
            continue

        baseline_values, center = _baseline(
            shares[lo:hi], _seasonal_samples(by_start, bucket.start, config)
        )
        sigma = _robust_sigma(baseline_values, center, bucket.total)
        zscore = (bucket.share - center) / sigma

        if (
            zscore >= config.z_threshold
            and bucket.hits >= config.min_hits
            and bucket.share > center
        ):
            spikes.append(
                Spike(
                    bucket_start=bucket.start,
                    hits=bucket.hits,
                    total=bucket.total,
                    share=bucket.share,
                    baseline=center,
                    zscore=zscore,
                    coverage=bucket.coverage,
                )
            )
    return spikes
