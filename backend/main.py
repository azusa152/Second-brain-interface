from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.dependencies import initialize_services
from backend.api.health_routes import router as health_router
from backend.api.index_routes import router as index_router
from backend.api.note_routes import router as note_router
from backend.api.search_routes import router as search_router
from backend.logging_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Initialize services on startup."""
    logger.info("Starting up: initializing services")
    initialize_services()
    yield
    logger.info("Shutting down")


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
