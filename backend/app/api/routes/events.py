"""Stories, rather than the individual words that gave them away."""
from fastapi import APIRouter, HTTPException, Query

from app.api.deps import EventDep
from app.core.horizons import HORIZONS
from app.schemas import Event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[Event])
def list_events(
    events: EventDep,
    limit: int = Query(50, ge=1, le=500),
    mode: str | None = Query(None, description="fast, mid or deep; omit for all"),
) -> list[Event]:
    return events.list_events(limit, mode)


@router.post("/rebuild")
def rebuild_events(
    events: EventDep,
    mode: str | None = Query(None, description=f"one of {', '.join(HORIZONS)}; omit for all"),
) -> dict:
    """Cluster term alerts into events, find each one's first post, flag repeats."""
    try:
        written = events.rebuild(mode) if mode else events.rebuild_all()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"events": written}


@router.get("/{mode}/{key:path}", response_model=Event)
def get_event(mode: str, key: str, events: EventDep) -> Event:
    event = events.get_event(key, mode)
    if event is None:
        raise HTTPException(status_code=404, detail="no such event")
    return event
