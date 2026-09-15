"""Dependency wiring. Routes ask for a service; nothing else constructs one."""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings
from app.db.database import create_connection
from app.db.repositories import (
    AlertsRepository,
    CountsRepository,
    EventsRepository,
    MatchesRepository,
    MetaRepository,
    SamplesRepository,
    TermsRepository,
    TrendsRepository,
)
from app.services.analytics_service import AnalyticsService
from app.services.benchmark_service import BenchmarkService
from app.services.detection_service import DetectionService
from app.services.event_service import EventService
from app.services.topic_service import TopicService


@lru_cache
def get_connection() -> sqlite3.Connection:
    """One shared read-mostly connection. SQLite in WAL mode handles this fine."""
    return create_connection(get_settings().database_path)


SettingsDep = Annotated[Settings, Depends(get_settings)]
ConnectionDep = Annotated[sqlite3.Connection, Depends(get_connection)]


def get_analytics_service(db: ConnectionDep, settings: SettingsDep) -> AnalyticsService:
    return AnalyticsService(
        CountsRepository(db), MatchesRepository(db), AlertsRepository(db),
        MetaRepository(db), TermsRepository(db), SamplesRepository(db),
        TrendsRepository(db), EventsRepository(db),
        TopicService(settings.topics_path), settings,
    )


def get_detection_service(db: ConnectionDep, settings: SettingsDep) -> DetectionService:
    return DetectionService(
        CountsRepository(db), MatchesRepository(db), AlertsRepository(db),
        TermsRepository(db), SamplesRepository(db), settings,
    )


def get_benchmark_service(db: ConnectionDep) -> BenchmarkService:
    return BenchmarkService(AlertsRepository(db), TrendsRepository(db))


def get_event_service(db: ConnectionDep, settings: SettingsDep) -> EventService:
    return EventService(
        AlertsRepository(db), EventsRepository(db), SamplesRepository(db), settings
    )


AnalyticsDep = Annotated[AnalyticsService, Depends(get_analytics_service)]
DetectionDep = Annotated[DetectionService, Depends(get_detection_service)]
BenchmarkDep = Annotated[BenchmarkService, Depends(get_benchmark_service)]
EventDep = Annotated[EventService, Depends(get_event_service)]
