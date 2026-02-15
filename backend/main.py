from fastapi import FastAPI

from backend.api.health_routes import router as health_router
from backend.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title="OpenClaw-Obsidian Knowledge Bridge",
    description="Local RAG middleware for semantic search over Obsidian vaults",
    version="0.1.0",
)

app.include_router(health_router)
