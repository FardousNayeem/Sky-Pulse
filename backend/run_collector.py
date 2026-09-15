#!/usr/bin/env python3
"""Ingest process entrypoint.

    python run_collector.py            # stream until Ctrl-C
    python run_collector.py --prune    # drop stored post text past retention, then stream
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from app.config import get_settings
from app.db.database import create_connection
from app.ingest.collector import Collector
from app.services.topic_service import TopicService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-16s %(message)s",
    datefmt="%H:%M:%S",
)


def _install_stop_handlers(stop: asyncio.Event) -> None:
    """Ask the loop to set `stop` on Ctrl-C, where the platform allows it.

    Windows' proactor loop has no add_signal_handler, so there Ctrl-C surfaces
    as KeyboardInterrupt out of asyncio.run instead. Either way the collector's
    `finally` flushes the buffer, so no data is lost.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError):
            pass


async def main_async(prune: bool) -> None:
    settings = get_settings()
    connection = create_connection(settings.database_path)
    matcher = TopicService(settings.topics_path).build_matcher()
    collector = Collector(connection, matcher, settings)

    if prune:
        collector.prune()

    stop = asyncio.Event()
    _install_stop_handlers(stop)

    await collector.run(stop)
    connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prune", action="store_true",
                        help="delete stored post text older than the retention window")
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args.prune))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
