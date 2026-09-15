"""Loads topic definitions and builds the matcher."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.matcher import Topic, TopicMatcher


class TopicService:
    """A topic in topics.json is either

        "name": ["phrase", ...]

    or, when it needs language scoping,

        "name": {"phrases": ["phrase", ...], "langs": ["en"]}
    """

    def __init__(self, topics_path: Path) -> None:
        self._path = topics_path

    @staticmethod
    def _parse(name: str, value: list | dict) -> Topic | None:
        if isinstance(value, list):
            return Topic(name=name, phrases=tuple(value))
        if isinstance(value, dict) and isinstance(value.get("phrases"), list):
            return Topic(
                name=name,
                phrases=tuple(value["phrases"]),
                langs=tuple(value.get("langs", ())),
            )
        return None

    def load(self) -> list[Topic]:
        with self._path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        topics = []
        for name, value in raw.items():
            if name.startswith("_"):
                continue
            topic = self._parse(name, value)
            if topic is not None:
                topics.append(topic)
        return topics

    def build_matcher(self) -> TopicMatcher:
        return TopicMatcher(self.load())
