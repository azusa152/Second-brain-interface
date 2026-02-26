import os
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.dependencies import get_index_service, get_scheduler, initialize_services
from backend.application.index_service import IndexService
from backend.api.augment_routes import router as augment_router
from backend.api.health_routes import router as health_router
from backend.api.index_routes import router as index_router
from backend.api.intent_routes import router as intent_router
from backend.api.note_routes import router as note_router
from backend.api.search_routes import router as search_router
from backend.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Initialize services on startup, start file watcher and scheduler, stop on shutdown."""
    logger.info("Starting up: initializing services")
    initialize_services()

    index_service = get_index_service()
    index_service.start_watcher()

    scheduler = get_scheduler()
    if scheduler is not None:
        await scheduler.start()

    _maybe_startup_incremental_rebuild(index_service)

    yield

    logger.info("Shutting down")
    index_service.stop_watcher()
    if scheduler is not None:
        await scheduler.stop()


def _maybe_startup_incremental_rebuild(index_service: IndexService) -> None:
    """Run incremental_rebuild in a background thread if STARTUP_INCREMENTAL_REBUILD is enabled."""
    enabled = os.getenv("STARTUP_INCREMENTAL_REBUILD", "true").lower() == "true"
    if not enabled:
        return
    logger.info("Running startup incremental rebuild in background thread")
    t = threading.Thread(
        target=index_service.incremental_rebuild,
        name="startup-incremental-rebuild",
        daemon=True,
    )
    t.start()


app = FastAPI(
    title="OpenClaw-Obsidian Knowledge Bridge",
    description="Local RAG middleware for semantic search over Obsidian vaults",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(index_router)
app.include_router(search_router)
app.include_router(note_router)
app.include_router(intent_router)
app.include_router(augment_router)

# Mount dashboard static files AFTER API routers (StaticFiles is a catch-all)
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/dashboard", StaticFiles(directory=_frontend_dir, html=True))
