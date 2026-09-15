"""Term discovery: what the stream is talking about, without being told first.

A fixed watchlist can only find what someone predicted. Real trends are proper
nouns nobody typed into a config file, so the terms have to come out of the
stream itself.

Counting every term exactly is unbounded - the vocabulary of a firehose grows
without limit. This keeps only the heavy hitters of each minute, which is
sufficient: a term outside the top of its own minute has nothing like the
volume a spike needs, so dropping it costs no recall.
"""
from __future__ import annotations

import re
from collections import Counter

from app.core.novelty import STOPWORDS

# Words, hashtags and internal apostrophes. Numbers are excluded: "2024" and
# "10" trend constantly and mean nothing on their own.
_TOKEN = re.compile(r"#?[a-z][a-z0-9'’_-]{1,29}")
_URL = re.compile(r"https?://\S+")
# Bluesky renders links without a scheme, so stripping http(s) alone leaves the
# host behind and "com", "www" and "org" become the heaviest terms in the feed.
_BARE_HOST = re.compile(r"\b[\w-]+(?:\.[\w-]+)+(?:/\S*)?")
_MENTION = re.compile(r"@[\w.-]+")

# The firehose is not English-only - Japanese, Portuguese, Spanish, German and
# French are all heavily represented - and a function word in any of them
# outranks every real subject by volume. These never spike, so they raise no
# false alerts; they crowd out the candidate budget, which is what this list is
# for. It is deliberately short: common function words only, no subject nouns.
MULTILINGUAL = frozenset("""
que de la el los las una uno con por para pero como mas muy sin sobre este esta eso
nao sim uma dos das nos meu minha voce isso aqui ainda quando porque tambem
der die das und ist nicht ein eine auch noch aber wenn sich schon nur mit auf
les des une est pas plus dans pour que qui vous nous mais comme tout tres sur
non piu sono anche perche questo quando
""".split())

# Contractions survive the base stoplist because it predates apostrophe tokens.
CONTRACTIONS = frozenset("""
i'm don't it's can't won't didn't doesn't isn't aren't wasn't weren't haven't hasn't
hadn't wouldn't couldn't shouldn't you're they're we're i've you've we've they've
i'll you'll he's she's that's there's what's let's ain't y'all i'd you'd
""".split())

# Calendar words trend every single day and mean nothing. They are not in the
# novelty stoplist because there they are harmless; as candidate subjects they
# waste the budget.
CALENDAR = frozenset("""
mon tue tues wed thu thur thurs fri sat sun monday tuesday wednesday thursday friday
saturday sunday jan feb mar apr jun jul aug sep sept oct nov dec january february
march april may june july august september october november december
am pm utc gmt est edt pst pdt today tomorrow yesterday
""".split())

# Stopwords are not enough on their own for bigrams: "of the" is two content-free
# words, and both halves have to be checked, not the pair.
MIN_TERM_LENGTH = 3


def words(text: str) -> list[str]:
    """Lowercased word tokens, with URLs, bare hosts and mentions removed."""
    text = _URL.sub(" ", text.lower())
    text = _BARE_HOST.sub(" ", text)
    text = _MENTION.sub(" ", text)
    return _TOKEN.findall(text)


def _is_content(word: str) -> bool:
    word = word.replace("’", "'")
    if word.startswith("#"):
        return len(word) > 2
    return (
        len(word) >= MIN_TERM_LENGTH
        and word not in STOPWORDS
        and word not in CALENDAR
        and word not in MULTILINGUAL
        and word not in CONTRACTIONS
    )


def extract_terms(text: str, tags: tuple[str, ...] = ()) -> set[str]:
    """Unigrams, bigrams and hashtags worth counting, deduplicated per post.

    Deduplicated because one post repeating a word ten times is one post
    talking about it, not ten. Counting occurrences would let a single ranting
    account manufacture a spike.

    Bigrams matter more than unigrams here: "lady gaga" is a subject, "lady"
    and "gaga" separately are noise. A bigram is kept when either half carries
    content, so "gaza ceasefire" and "the ceasefire" both survive while "of
    the" does not.
    """
    tokens = words(text)
    terms: set[str] = {w for w in tokens if _is_content(w)}

    for left, right in zip(tokens, tokens[1:]):
        if len(left) < 2 or len(right) < 2:
            continue
        if left.startswith("#") or right.startswith("#"):
            continue
        if _is_content(left) or _is_content(right):
            terms.add(f"{left} {right}")

    for tag in tags:
        tag = tag.strip().lower()
        if tag:
            terms.add(f"#{tag.lstrip('#')}")

    return terms


class TopTerms:
    """Approximate top-k counter over a minute of the stream.

    Lossy counting rather than exact Space-Saving: counts accumulate in a plain
    dict, and when it grows past `capacity` the tail is dropped in one pass.
    Space-Saving's per-miss minimum search is O(n) on every new term, which at
    this arrival rate costs more than the periodic prune does, and the guarantee
    it buys - a bounded error on terms that were never frequent - is not worth
    paying for when those terms are discarded anyway.

    A term that is genuinely heavy survives every prune, because it is never in
    the tail. A term pruned and later re-seen restarts from zero, which
    understates it slightly; that only ever suppresses an alert, never invents
    one.
    """

    def __init__(self, capacity: int = 20_000) -> None:
        self._counts: Counter = Counter()
        self._seen: set[int] = set()
        self._capacity = capacity
        # Pruning at exactly `capacity` would re-prune on nearly every add once
        # full. Letting it fill to twice that amortises the pass.
        self._high_water = capacity * 2

    def add(self, terms: set[str], author: str = "") -> None:
        """Count each term once per author per minute.

        Without this a single automated account posting the same template
        hundreds of times an hour is indistinguishable from a story breaking -
        and on this firehose there are several of them. Counting distinct
        authors makes a spike mean "many people started saying this", which is
        the only thing worth alerting on.

        Membership is stored as hashes rather than pairs: the exact strings are
        never needed again, and a minute of the firehose is a lot of tuples.
        """
        if not author:
            self._counts.update(terms)
        else:
            fresh = [t for t in terms if hash((t, author)) not in self._seen]
            self._seen.update(hash((t, author)) for t in terms)
            self._counts.update(fresh)
        if len(self._counts) > self._high_water:
            self._prune()

    def _prune(self) -> None:
        self._counts = Counter(dict(self._counts.most_common(self._capacity)))

    def top(self, limit: int, min_hits: int = 1) -> dict[str, int]:
        return {
            term: hits
            for term, hits in self._counts.most_common(limit)
            if hits >= min_hits
        }

    def clear(self) -> None:
        self._counts.clear()
        self._seen.clear()

    def __len__(self) -> int:
        return len(self._counts)
