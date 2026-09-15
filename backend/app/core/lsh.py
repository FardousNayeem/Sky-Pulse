"""First story detection: which post said it first.

"A term spiked" is a measurement. "This post started it, at 14:22" is the thing
a person actually wants, and it is the one artifact a detector can hand over
that needs no further work.

The method is Petrović, Osborne and Lavrenko's streaming first story detection:
hash every post, compare each new one only against the handful that hash
nearby, and call it a first story when nothing near it has been seen. Locality
-sensitive hashing is what makes that affordable - it replaces comparing
against everything with comparing against a bucket.

It is hashing, not inference. No model, no dependency, nothing per post beyond
arithmetic, so it costs nothing to run.
"""
from __future__ import annotations

from collections import defaultdict
from zlib import crc32

from app.core.terms import words

SIGNATURE_SIZE = 64
BAND_COUNT = 16          # 16 bands of 4 rows: candidates at roughly 0.5 similarity
ROWS_PER_BAND = SIGNATURE_SIZE // BAND_COUNT
MAX_HASH = 0xFFFFFFFF

# Below this, nothing already seen resembles the post, so it is saying
# something new rather than repeating it.
NOVELTY_THRESHOLD = 0.4


def shingles(text: str) -> set[str]:
    """Adjacent word pairs.

    Pairs rather than single words because near-duplicates are what matter
    here: two posts about the same event share vocabulary, but two posts
    carrying the *same sentence* share its word order, and only the second is a
    repeat rather than a first telling.
    """
    tokens = words(text)
    if len(tokens) < 2:
        return set(tokens)
    return {f"{a} {b}" for a, b in zip(tokens, tokens[1:])}


def signature(items: set[str]) -> tuple[int, ...]:
    """MinHash signature.

    crc32 with a per-permutation seed rather than Python's hash(): the built-in
    is salted per process, so signatures would not survive a restart and two
    runs over the same post would disagree.
    """
    if not items:
        return tuple([MAX_HASH] * SIGNATURE_SIZE)
    encoded = [item.encode("utf-8") for item in items]
    return tuple(
        min(crc32(item, seed) for item in encoded)
        for seed in range(SIGNATURE_SIZE)
    )


def similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    """Estimated Jaccard: the fraction of the signature that agrees."""
    same = sum(1 for a, b in zip(left, right) if a == b)
    return same / len(left)


class LshIndex:
    """Near-duplicate lookup by banded signature.

    Two posts land in the same bucket when any band of their signatures matches
    exactly, which happens with probability rising sharply around the band
    threshold. That turns "compare against everything seen" into "compare
    against a few", which is the whole point.
    """

    def __init__(self) -> None:
        self._bands: list[dict[tuple, list[int]]] = [defaultdict(list) for _ in range(BAND_COUNT)]
        self._signatures: dict[int, tuple[int, ...]] = {}
        self._next_id = 0

    def add(self, sig: tuple[int, ...]) -> int:
        key = self._next_id
        self._next_id += 1
        self._signatures[key] = sig
        for band, table in enumerate(self._bands):
            table[self._band_key(sig, band)].append(key)
        return key

    def nearest(self, sig: tuple[int, ...]) -> float:
        """Highest similarity to anything already indexed. 0.0 when empty."""
        seen: set[int] = set()
        for band, table in enumerate(self._bands):
            seen.update(table.get(self._band_key(sig, band), ()))
        if not seen:
            return 0.0
        return max(similarity(sig, self._signatures[key]) for key in seen)

    @staticmethod
    def _band_key(sig: tuple[int, ...], band: int) -> tuple:
        start = band * ROWS_PER_BAND
        return (band, *sig[start:start + ROWS_PER_BAND])

    def __len__(self) -> int:
        return len(self._signatures)


def first_story(
    candidates: list[tuple[int, str, str, str]],
    background: list[str],
    threshold: float = NOVELTY_THRESHOLD,
) -> tuple[tuple[int, str, str, str], float] | None:
    """The earliest candidate that was not already being said.

    `candidates` are (ts, did, rkey, text) from the spike, `background` the
    posts from before it. Walking forward in time, the first candidate with no
    near neighbour - in the background or among the candidates already walked -
    is the first telling of the story.

    Returns None when every candidate resembles something already there, which
    is the honest answer for a spike that is a continuation rather than a
    beginning.
    """
    index = LshIndex()
    for text in background:
        index.add(signature(shingles(text)))

    for candidate in sorted(candidates, key=lambda c: c[0]):
        sig = signature(shingles(candidate[3]))
        nearest = index.nearest(sig)
        if nearest < threshold:
            return candidate, round(1.0 - nearest, 3)
        index.add(sig)
    return None
