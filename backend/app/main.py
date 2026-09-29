"""FastAPI app: routes, startup wiring, and the built frontend in production."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, scheduler
from app.config import settings
from app.db import init_db, session_scope
from app.llm import embedder, llm
from app.routers import cv, jobs, runs, settings as settings_router
from app.schemas import HealthOut
from app.settings_store import ensure_settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

#: Populated when the frontend has been built into backend/static (Docker image).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with session_scope() as db:
        config = ensure_settings(db)

    if not llm.available:
        logger.warning(
            "OPENAI_API_KEY is not set. Fetching, dedup and the similarity "
            "prefilter still work; scoring, language judgment "
            "are disabled."
        )
    logger.info("Chat model: %s | embedding backend: %s", llm.model, embedder.label)

    scheduler.start(config)
    scheduler.catch_up_if_needed(config)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(
    title="Job Portal",
    description="Personal job search pipeline: collect, score, filter, draft, track.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(runs.router)
app.include_router(settings_router.router)
app.include_router(cv.router)


@app.get("/api/health", response_model=HealthOut, tags=["meta"])
def health() -> HealthOut:
    return HealthOut(
        version=__version__,
        llm_enabled=llm.available,
        scheduler_running=scheduler.is_running(),
        next_run=scheduler.next_run_time(),
    )


if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the SPA, letting client-side routing own every non-API path."""
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
