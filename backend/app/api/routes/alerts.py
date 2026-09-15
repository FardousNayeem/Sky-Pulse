from fastapi import APIRouter, HTTPException, Query

from app.api.deps import BenchmarkDep, DetectionDep
from app.core.horizons import HORIZONS
from app.schemas import Alert, BenchmarkReport, DetectionRun, HorizonStatus

router = APIRouter(tags=["alerts"])

KINDS = ("topic", "term")


@router.get("/horizons", response_model=list[HorizonStatus])
def list_horizons(detection: DetectionDep) -> list[HorizonStatus]:
    """Each detection horizon, its warm-up, and whether it can run yet."""
    return detection.horizons()


@router.get("/alerts", response_model=list[Alert])
def list_alerts(
    detection: DetectionDep,
    limit: int = Query(100, ge=1, le=500),
    subject: str | None = Query(None, description="a topic name or a discovered term"),
    mode: str | None = Query(None, description="fast, mid or deep; omit for all horizons"),
    kind: str | None = Query(None, description=f"one of {', '.join(KINDS)}; omit for both"),
    sort: str = Query("recent", description="'recent' or 'confidence'"),
) -> list[Alert]:
    try:
        return detection.list_alerts(limit, subject, mode, kind, sort)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/detect", response_model=list[DetectionRun])
def run_detection(
    detection: DetectionDep,
    mode: str | None = Query(
        None, description=f"one of {', '.join(HORIZONS)}; omit to run every horizon"
    ),
    kind: str | None = Query(None, description=f"one of {', '.join(KINDS)}; omit for both"),
    subject: str | None = None,
) -> list[DetectionRun]:
    """Score buckets against their trailing baselines and persist new spikes.

    Scoring is retroactive: a horizon scores all of history each time it runs,
    so history collected before this endpoint existed is not lost.
    """
    try:
        if mode:
            return [detection.run(mode, subject, kind)]
        runs = detection.run_all(subject)
        return [r for r in runs if not kind or r.kind == kind]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/benchmark", response_model=BenchmarkReport)
def get_benchmark(
    benchmark: BenchmarkDep,
    limit: int = Query(100, ge=1, le=500),
) -> BenchmarkReport:
    """This detector against Bluesky's own trending list.

    Lead time is the measure: minutes between sky-pulse raising a spike and
    the platform listing the same story. Positive means ahead.
    """
    return benchmark.report(limit)


@router.get("/model")
def get_model(detection: DetectionDep) -> dict:
    """The confidence model, or null when none has been fitted yet.

    Null is the normal state early on: a model needs enough past spikes old
    enough to know whether they held.
    """
    return {"model": detection.model_info()}
