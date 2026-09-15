"""Explain a spike: which words are unusually common in it. Pure logic."""
from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"[a-z][a-z']{2,}")

STOPWORDS = frozenset("""
a an the and or but if then than that this these those is are was were be been being am do does did
doing have has had having i you he she it we they me him her them my your his its our their of in on
at to for with from by about as into like through after before between out up down off over under
again further once here there when where why how all any both each few more most other some such no
nor not only own same so too very can will just dont should now got get im it's rt http https new one
two make made way say says said people time day today what who dont cant wont thats theres
""".split())

MIN_TERM_OCCURRENCES = 2
MIN_LIFT = 3.0


def _tokenize(texts: list[str]) -> Counter:
    counts: Counter = Counter()
    for text in texts:
        for word in _WORD.findall(text.lower()):
            if word not in STOPWORDS:
                counts[word] += 1
    return counts


def distinctive_terms(inside: list[str], outside: list[str], limit: int = 6) -> list[str]:
    """Terms far more frequent inside the spike than in the topic's usual chatter.

    `inside`  - post texts from the spiking window
    `outside` - post texts for the same topic from other windows
    """
    if not inside:
        return []

    inside_counts = _tokenize(inside)
    outside_counts = _tokenize(outside)
    inside_total = max(sum(inside_counts.values()), 1)
    outside_total = max(sum(outside_counts.values()), 1)

    scored: list[tuple[float, str]] = []
    for word, count in inside_counts.items():
        if count < MIN_TERM_OCCURRENCES:
            continue
        inside_rate = count / inside_total
        outside_rate = outside_counts.get(word, 0) / outside_total
        lift = inside_rate / (outside_rate + 1e-9)
        if lift >= MIN_LIFT:
            scored.append((lift, word))

    scored.sort(reverse=True)
    return [word for _, word in scored[:limit]]


MIN_LINK_SHARE = 0.02


def top_links(link_fields: list[str], limit: int = 3) -> list[str]:
    """The URLs most shared inside a spike.

    When a thousand people start posting at once they are usually posting the
    same story, so the most-shared link is the explanation - a headline rather
    than a bag of words. A URL carried by a couple of posts out of hundreds is
    coincidence, so a link has to account for a small share of the window
    before it is offered as the reason for anything.
    """
    counts: Counter = Counter()
    posts_with_links = 0
    for field in link_fields:
        urls = {url for url in field.split() if url.startswith("http")}
        if urls:
            posts_with_links += 1
            counts.update(urls)
    if not counts:
        return []

    floor = max(2, int(posts_with_links * MIN_LINK_SHARE))
    return [url for url, count in counts.most_common(limit) if count >= floor]
