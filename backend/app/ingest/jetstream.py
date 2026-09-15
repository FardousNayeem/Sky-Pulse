"""Jetstream websocket transport. Knows the wire protocol, nothing else.

Yields PostEvent objects. Reconnects with exponential backoff, rotating hosts,
and resumes from the last cursor when it is recent enough to be worth replaying.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import websockets

log = logging.getLogger("pulse.jetstream")

RECV_TIMEOUT = 30
OPEN_TIMEOUT = 20
MAX_BACKOFF = 60


@dataclass(frozen=True)
class PostEvent:
    did: str
    rkey: str
    text: str
    lang: str | None
    time_us: int
    links: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def timestamp(self) -> int:
        return self.time_us // 1_000_000


def _facets(record: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Links and hashtags carried by a post.

    These arrive in the bytes already being read, so collecting them costs
    nothing extra on the wire. A link is the cheapest explanation of a spike
    there is: when a thousand people start posting at once, they are usually
    posting the same story.

    Two places carry a URL - richtext facets, for links written into the text,
    and an external embed, for the link card underneath it. A post often has
    both, pointing at the same place, so the result is deduplicated.
    """
    links: list[str] = []
    tags: list[str] = []

    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            kind = feature.get("$type", "")
            if kind.endswith("#link") and feature.get("uri"):
                links.append(feature["uri"])
            elif kind.endswith("#tag") and feature.get("tag"):
                tags.append(feature["tag"])

    embed = record.get("embed") or {}
    if embed.get("$type", "").startswith("app.bsky.embed.external"):
        uri = (embed.get("external") or {}).get("uri")
        if uri:
            links.append(uri)

    for tag in record.get("tags") or []:
        if isinstance(tag, str) and tag:
            tags.append(tag)

    return tuple(dict.fromkeys(links)), tuple(dict.fromkeys(tags))


class JetstreamClient:
    def __init__(
        self,
        hosts: tuple[str, ...],
        collection: str,
        max_cursor_age_seconds: int = 3600,
    ) -> None:
        self._hosts = hosts
        self._collection = collection
        self._max_cursor_age_us = max_cursor_age_seconds * 1_000_000
        self.cursor: int | None = None

    def resume_from(self, cursor: str | int | None) -> None:
        """Adopt a saved cursor, unless it is too stale to catch up on."""
        if not cursor:
            return
        cursor = int(cursor)
        age_us = time.time() * 1_000_000 - cursor
        if age_us > self._max_cursor_age_us:
            log.info("saved cursor is %.1fh old - starting live", age_us / 3.6e9)
            return
        log.info("resuming %.1f minutes behind live", age_us / 6e7)
        self.cursor = cursor

    def _url(self, host: str) -> str:
        url = f"{host}?collections={self._collection}"
        if self.cursor:
            url += f"&cursor={self.cursor}"
        return url

    @staticmethod
    def _parse(raw: str, collection: str) -> PostEvent | None:
        event = json.loads(raw)
        if event.get("kind") != "commit":
            return None
        commit = event.get("commit") or {}
        if commit.get("operation") != "create" or commit.get("collection") != collection:
            return None
        record = commit.get("record") or {}
        text = (record.get("text") or "").strip()
        if not text:
            # ~87% of post commits carry no text. They are not corpus.
            return None
        langs = record.get("langs") or []
        links, tags = _facets(record)
        return PostEvent(
            did=event.get("did", ""),
            rkey=commit.get("rkey", ""),
            text=text,
            lang=langs[0] if langs else None,
            time_us=event.get("time_us") or int(time.time() * 1_000_000),
            links=links,
            tags=tags,
        )

    async def stream(self, stop: asyncio.Event) -> AsyncIterator[PostEvent]:
        backoff = 1
        host_index = 0

        while not stop.is_set():
            host = self._hosts[host_index % len(self._hosts)]
            try:
                async with websockets.connect(
                    self._url(host), open_timeout=OPEN_TIMEOUT,
                    ping_interval=20, max_queue=4096,
                ) as socket:
                    log.info("connected to %s", host)
                    backoff = 1
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=RECV_TIMEOUT)
                        except asyncio.TimeoutError:
                            log.warning("no data for %ss - reconnecting", RECV_TIMEOUT)
                            break
                        event = self._parse(raw, self._collection)
                        if event is not None:
                            self.cursor = event.time_us
                            yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any transport error is retryable
                if stop.is_set():
                    break
                log.warning("%s: %s - retrying in %ss", type(exc).__name__, exc, backoff)
                host_index += 1
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, MAX_BACKOFF)
