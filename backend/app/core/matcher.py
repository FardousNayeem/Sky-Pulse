"""Topic matching. Pure logic - no I/O, no framework, no database."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Topic:
    name: str
    phrases: tuple[str, ...]
    # Empty means "any language". Set it for short or cross-language ambiguous
    # tokens - "ai" is the AI topic in English but an interjection in Portuguese.
    langs: tuple[str, ...] = field(default=())


class TopicMatcher:
    """Matches post text against a set of topics.

    Phrases are literal, not regex. A phrase is bounded so it cannot match
    inside a longer word. Plain \\b is not enough: it treats an apostrophe as a
    boundary, so \\bai\\b matches the French "j'ai". These lookarounds also
    reject a neighbouring apostrophe, removing a large class of cross-language
    false positives.
    """

    LEFT_EDGE = r"(?<![\w'’])"
    RIGHT_EDGE = r"(?![\w'’])"

    def __init__(self, topics: list[Topic]) -> None:
        self._patterns: dict[str, re.Pattern[str]] = {}
        self._langs: dict[str, tuple[str, ...]] = {}
        for topic in topics:
            pattern = self._compile(topic.phrases)
            if pattern is not None:
                self._patterns[topic.name] = pattern
                self._langs[topic.name] = topic.langs

    @classmethod
    def _compile(cls, phrases: tuple[str, ...]) -> re.Pattern[str] | None:
        parts = []
        for phrase in phrases:
            phrase = phrase.strip()
            if not phrase:
                continue
            left = cls.LEFT_EDGE if phrase[0].isalnum() else ""
            right = cls.RIGHT_EDGE if phrase[-1].isalnum() else ""
            parts.append(f"{left}{re.escape(phrase)}{right}")
        if not parts:
            return None
        return re.compile("|".join(parts), re.IGNORECASE)

    @property
    def topic_names(self) -> list[str]:
        return sorted(self._patterns)

    def match(self, text: str, lang: str | None = None) -> list[str]:
        """Return every topic whose pattern occurs in the text.

        A topic that declares `langs` only matches posts tagged with one of
        them. Posts with no language tag are not excluded, since roughly a
        third of the firehose carries none.
        """
        hits = []
        for name, pattern in self._patterns.items():
            allowed = self._langs.get(name, ())
            if allowed and lang is not None and lang not in allowed:
                continue
            if pattern.search(text):
                hits.append(name)
        return hits
