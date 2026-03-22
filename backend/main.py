import os
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.api.augment_routes import router as augment_router
from backend.api.config_routes import router as config_router
from backend.api.debug_routes import router as debug_router
from backend.api.dependencies import get_index_service, get_scheduler, initialize_services
from backend.api.health_routes import router as health_router
from backend.api.index_routes import router as index_router
from backend.api.intent_routes import router as intent_router
from backend.api.middleware import AccessLogMiddleware, RequestIDMiddleware
from backend.api.note_routes import router as note_router
from backend.api.search_routes import router as search_router
from backend.application.index_service import IndexService
from backend.config import get_settings
from backend.logging_config import get_logger, setup_logging

setup_logging()
_settings = get_settings()
setup_logging(log_level=_settings.log_level, json_output=_settings.log_format == "json")
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
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
    if not get_settings().startup_incremental_rebuild:
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

# CORS — permits the dashboard (served at /dashboard) and any local LLM agent
# to call the API directly from a browser context.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AccessLogMiddleware, skip_paths={"/health"})
app.add_middleware(RequestIDMiddleware)

app.include_router(health_router)
app.include_router(config_router)
if _settings.debug_endpoints:
    app.include_router(debug_router)
app.include_router(index_router)
app.include_router(search_router)
app.include_router(note_router)
app.include_router(intent_router)
app.include_router(augment_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured 500 response for any unhandled exception."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
        },
    )


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles with no-cache to force browser revalidation."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


# Mount dashboard static files AFTER API routers (StaticFiles is a catch-all).
# The root redirect is registered in the same guard so both features stay in sync:
# if the frontend directory is absent, neither the redirect nor the static mount exists.
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/dashboard/", status_code=307)

    app.mount("/dashboard", NoCacheStaticFiles(directory=_frontend_dir, html=True))
