from fastapi import APIRouter, Query

from app.api.deps import AnalyticsDep
from app.schemas import Post, TopicSeries, TopicSummary

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=list[TopicSummary])
def list_topics(analytics: AnalyticsDep) -> list[TopicSummary]:
    return analytics.topics()


@router.get("/{topic}/series", response_model=TopicSeries)
def topic_series(
    topic: str,
    analytics: AnalyticsDep,
    bucket_minutes: int = Query(15, ge=1, le=1440),
    limit: int = Query(200, ge=1, le=2000),
) -> TopicSeries:
    """Share-of-conversation over time for one topic."""
    return analytics.series(topic, bucket_minutes, limit)


@router.get("/{topic}/posts", response_model=list[Post])
def topic_posts(
    topic: str,
    analytics: AnalyticsDep,
    limit: int = Query(50, ge=1, le=500),
    start: int | None = Query(None, description="unix seconds, window start"),
    end: int | None = Query(None, description="unix seconds, window end"),
) -> list[Post]:
    """Recent posts for a topic, or the posts inside a specific alert window."""
    return analytics.posts(topic, limit, start, end)
