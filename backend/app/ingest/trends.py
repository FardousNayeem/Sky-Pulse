"""Bluesky's own trending topics, polled from the public API.

Ground truth. Until this existed there was no way to say whether a spike this
detector raised was real, and no way to tune a threshold except by taste.

The endpoint is public, unauthenticated and unmetered, like the firehose, so
polling it costs nothing and breaks no constraint. It is also the competitor:
the useful claim is not "we found a trend" but "we found it N minutes before
the platform did", and that number cannot be computed without this table.
"""
from __future__ import annotations

import http.client
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

log = logging.getLogger("pulse.trends")

TIMEOUT = 15
USER_AGENT = "sky-pulse/1.0 (+https://github.com/)"


def _epoch(value: Any) -> int | None:
    """ISO-8601 with a Z or an offset, as the API returns it."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def fetch_trends(url: str, limit: int, now: int) -> list[tuple]:
    """Rows ready for TrendsRepository.upsert, or an empty list on any failure.

    Network trouble here must never disturb ingest: the trends table is an
    evaluation aid, and a gap in it costs a benchmark row, not a measurement.
    """
    request = urllib.request.Request(
        f"{url}?limit={limit}", headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        # A truncated response is http.client.IncompleteRead, which is an
        # HTTPException rather than an OSError - so it escapes the obvious
        # handler and surfaces as a traceback for what is a routine hiccup.
        http.client.HTTPException,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        log.warning("could not fetch trends: %s", exc)
        return []

    rows = []
    for trend in payload.get("trends") or []:
        topic = trend.get("topic") or trend.get("displayName")
        if not topic:
            continue
        rows.append((
            str(topic),
            str(trend.get("displayName") or topic),
            str(trend.get("description") or ""),
            str(trend.get("category") or ""),
            str(trend.get("status") or ""),
            int(trend.get("postCount") or 0),
            _epoch(trend.get("startedAt")),
            now,
            now,
        ))
    return rows
