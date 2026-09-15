from fastapi import APIRouter

from app.api.deps import AnalyticsDep
from app.schemas import CorpusStats

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=CorpusStats)
def get_stats(analytics: AnalyticsDep) -> CorpusStats:
    """How much has been collected, and is the collector alive right now."""
    return analytics.stats()
