"""Features for one spike, and the label used to learn from it.

Everything here is computable at the moment the spike is scored. Nothing reads
a bucket later than the one being scored, because a feature that peeks at the
future would train a model that cannot be run in production - it would look
excellent in evaluation and predict nothing live.

The label is the exception, and deliberately so: it is read from the future,
during training only.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from app.core.detector import Bucket, Spike

FEATURE_NAMES = [
    "log_hits",
    "zscore",
    "log_multiple",
    "baseline_silent",
    "share_per_mille",
    "coverage",
    "is_term",
    "is_multiword",
    "is_hashtag",
    "n_terms",
    "n_links",
    "log_bucket_minutes",
    "history_density",
    "log_window_posts",
    "hour_sin",
    "hour_cos",
]

# A z-score off a near-silent baseline is unbounded and would otherwise be the
# only feature with any weight. The cap keeps it comparable to the rest.
ZSCORE_CAP = 50.0


def spike_features(
    spike: Spike,
    buckets: list[Bucket],
    index: int,
    bucket_minutes: int,
    kind: str,
    subject: str,
    terms: list[str],
    links: list[str],
) -> list[float]:
    """One row, in FEATURE_NAMES order."""
    baseline_silent = 1.0 if spike.baseline <= 0 else 0.0
    multiple = spike.share / spike.baseline if spike.baseline > 0 else 0.0

    # How established the subject already was. A word that has been present all
    # along behaves differently from one appearing for the first time, and the
    # z-score alone cannot tell them apart.
    prior = buckets[max(0, index - 32):index]
    density = sum(1 for b in prior if b.hits > 0) / len(prior) if prior else 0.0

    hour = datetime.fromtimestamp(spike.bucket_start, timezone.utc).hour
    angle = 2 * math.pi * hour / 24

    return [
        math.log1p(spike.hits),
        min(spike.zscore, ZSCORE_CAP),
        math.log1p(multiple),
        baseline_silent,
        spike.share * 1000,
        spike.coverage,
        1.0 if kind == "term" else 0.0,
        1.0 if " " in subject else 0.0,
        1.0 if subject.startswith("#") else 0.0,
        float(len(terms)),
        float(len(links)),
        math.log1p(bucket_minutes),
        density,
        math.log1p(spike.total),
        math.sin(angle),
        math.cos(angle),
    ]


LOOKAHEAD = 3
MIN_SUSTAINED = 2
SUSTAIN_FRACTION = 0.5


def persistence_label(spike: Spike, buckets: list[Bucket], index: int) -> int | None:
    """Did the spike hold, or did it revert immediately?

    This is the label available without waiting for anyone else to confirm
    anything. A real story stays elevated for a while; a blip is back to
    baseline in the next bucket. It is a proxy for importance, not importance
    itself - it learns what persists, which is not quite the same as what
    matters - but it is checkable, it needs no external service, and it is
    exactly the property that makes an alert worth showing a person.

    Returns None when the future needed to judge it has not been collected
    yet. Those spikes are not training data.
    """
    excess = spike.share - spike.baseline
    if excess <= 0:
        return None

    future = buckets[index + 1: index + 1 + LOOKAHEAD]
    if len(future) < LOOKAHEAD:
        return None

    sustained = sum(
        1 for b in future if (b.share - spike.baseline) >= SUSTAIN_FRACTION * excess
    )
    return 1 if sustained >= MIN_SUSTAINED else 0
