"""Logistic regression in plain Python. No dependency, no per-post cost.

Inference is a dot product over a dozen features, run once per candidate spike
rather than once per post, so it does not touch the hot path and nothing bills.
Training is batch gradient descent over a few hundred rows, which takes
milliseconds; there is no reason to pull in a numerical stack for it.

The model exists to replace hand-set thresholds with a calibrated probability.
A z-score says how far from normal something is, which is not the same question
as whether it matters - the thresholds in horizons.py were guesses about how
those relate, and this learns the relation instead.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

LEARNING_RATE = 0.3
EPOCHS = 4000
L2 = 0.01


def _sigmoid(z: float) -> float:
    # Guarded because exp overflows for large negative z on the way to 0.
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass
class Standardizer:
    """Zero-mean, unit-variance per feature.

    Features here span wildly different scales - a z-score of 300 next to a
    0/1 flag - and without this the large ones dominate the gradient and the
    small ones never get a coefficient worth reading.
    """

    mean: list[float] = field(default_factory=list)
    std: list[float] = field(default_factory=list)

    @classmethod
    def fit(cls, rows: list[list[float]]) -> Standardizer:
        n = len(rows)
        width = len(rows[0])
        mean = [sum(r[i] for r in rows) / n for i in range(width)]
        std = []
        for i in range(width):
            var = sum((r[i] - mean[i]) ** 2 for r in rows) / n
            # A constant feature has no spread; dividing by it would be
            # infinite, and it carries no information anyway.
            std.append(math.sqrt(var) if var > 1e-12 else 1.0)
        return cls(mean, std)

    def apply(self, row: list[float]) -> list[float]:
        return [(v - m) / s for v, m, s in zip(row, self.mean, self.std)]


@dataclass
class LogisticModel:
    feature_names: list[str]
    weights: list[float]
    bias: float
    standardizer: Standardizer
    trained_on: int = 0
    positives: int = 0
    accuracy: float = 0.0
    auc: float = 0.0
    holdout_auc: float | None = None
    holdout_size: int = 0
    label: str = ""

    def predict(self, row: list[float]) -> float:
        scaled = self.standardizer.apply(row)
        z = self.bias + sum(w * v for w, v in zip(self.weights, scaled))
        return _sigmoid(z)

    def top_factors(self, limit: int = 5) -> list[tuple[str, float]]:
        """Which features move the decision most, largest first."""
        pairs = sorted(
            zip(self.feature_names, self.weights), key=lambda p: abs(p[1]), reverse=True
        )
        return [(name, round(w, 3)) for name, w in pairs[:limit]]

    def to_dict(self) -> dict:
        return {
            "feature_names": self.feature_names,
            "weights": self.weights,
            "bias": self.bias,
            "mean": self.standardizer.mean,
            "std": self.standardizer.std,
            "trained_on": self.trained_on,
            "positives": self.positives,
            "accuracy": self.accuracy,
            "auc": self.auc,
            "holdout_auc": self.holdout_auc,
            "holdout_size": self.holdout_size,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict) -> LogisticModel:
        return cls(
            feature_names=data["feature_names"],
            weights=data["weights"],
            bias=data["bias"],
            standardizer=Standardizer(data["mean"], data["std"]),
            trained_on=data.get("trained_on", 0),
            positives=data.get("positives", 0),
            accuracy=data.get("accuracy", 0.0),
            auc=data.get("auc", 0.0),
            holdout_auc=data.get("holdout_auc"),
            holdout_size=data.get("holdout_size", 0),
            label=data.get("label", ""),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> LogisticModel | None:
        """Returns None when there is no model yet, which is the normal state
        until enough history has been collected to train one."""
        try:
            return cls.from_dict(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError):
            return None


def auc_score(labels: list[int], scores: list[float]) -> float:
    """Probability a random positive outranks a random negative.

    Reported instead of accuracy alone because these classes are unbalanced:
    a model that answers "no" every time can look accurate and be useless.
    """
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return 0.5
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0
        for p in pos
        for n in neg
    )
    return wins / (len(pos) * len(neg))


def train(
    rows: list[list[float]],
    labels: list[int],
    feature_names: list[str],
    label_name: str = "",
) -> LogisticModel:
    """Fit by batch gradient descent with L2 shrinkage.

    Class weighting rather than resampling: positives are the minority, and
    without it the cheapest way to cut the loss is to predict "no" forever.
    """
    standardizer = Standardizer.fit(rows)
    scaled = [standardizer.apply(r) for r in rows]
    width = len(feature_names)
    weights = [0.0] * width
    bias = 0.0

    n_pos = sum(labels) or 1
    n_neg = len(labels) - n_pos or 1
    weight_of = {1: len(labels) / (2 * n_pos), 0: len(labels) / (2 * n_neg)}
    total_weight = sum(weight_of[y] for y in labels)

    for _ in range(EPOCHS):
        grad = [0.0] * width
        grad_bias = 0.0
        for row, y in zip(scaled, labels):
            w = weight_of[y]
            error = (_sigmoid(bias + sum(wi * v for wi, v in zip(weights, row))) - y) * w
            grad_bias += error
            for i, v in enumerate(row):
                grad[i] += error * v
        bias -= LEARNING_RATE * grad_bias / total_weight
        for i in range(width):
            weights[i] -= LEARNING_RATE * (grad[i] / total_weight + L2 * weights[i])

    model = LogisticModel(feature_names, weights, bias, standardizer, label=label_name)
    scores = [model.predict(r) for r in rows]
    model.trained_on = len(rows)
    model.positives = sum(labels)
    model.accuracy = round(
        sum(1 for s, y in zip(scores, labels) if (s >= 0.5) == bool(y)) / len(rows), 3
    )
    model.auc = round(auc_score(labels, scores), 3)
    return model
