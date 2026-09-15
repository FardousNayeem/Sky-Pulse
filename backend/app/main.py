"""FastAPI application. Wiring only - no logic lives in this file."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import alerts, events, stats, terms, topics
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="sky-pulse",
    description="Detects unusual spikes in Bluesky conversation topics.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stats.router, prefix="/api")
app.include_router(topics.router, prefix="/api")
app.include_router(terms.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
