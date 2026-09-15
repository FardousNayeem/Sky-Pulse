"""Terms discovered in the stream, as opposed to topics declared in advance."""
from fastapi import APIRouter, Query

from app.api.deps import AnalyticsDep
from app.schemas import Post, TopicSeries

router = APIRouter(prefix="/terms", tags=["terms"])


@router.get("/{term}/series", response_model=TopicSeries)
def term_series(
    term: str,
    analytics: AnalyticsDep,
    bucket_minutes: int = Query(4, ge=1, le=1440),
    limit: int = Query(200, ge=1, le=2000),
) -> TopicSeries:
    """Share of conversation over time for one discovered term."""
    return analytics.term_series(term, bucket_minutes, limit)


@router.get("/{term}/posts", response_model=list[Post])
def term_posts(
    term: str,
    analytics: AnalyticsDep,
    limit: int = Query(50, ge=1, le=500),
    start: int | None = Query(None, description="unix seconds, window start"),
    end: int | None = Query(None, description="unix seconds, window end"),
) -> list[Post]:
    """Sampled posts mentioning a term, or those inside an alert's window."""
    return analytics.term_posts(term, limit, start, end)
