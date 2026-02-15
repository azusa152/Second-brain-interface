import os

from backend.application.index_service import IndexService
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.qdrant_adapter import QdrantAdapter
from backend.infrastructure.vault_file_map import VaultFileMap
from backend.logging_config import get_logger

logger = get_logger(__name__)

_index_service: IndexService | None = None


def initialize_services() -> None:
    """Initialize all services at startup. Called from FastAPI lifespan."""
    get_index_service()


def get_index_service() -> IndexService:
    """Return the singleton IndexService, creating it on first call."""
    global _index_service  # noqa: PLW0603
    if _index_service is None:
        vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "/vault")
        logger.info("Initializing IndexService with vault: %s", vault_path)

        vault_file_map = VaultFileMap(vault_path)
        parser = MarkdownParser(vault_file_map)
        chunker = Chunker()
        embedder = EmbeddingService()
        qdrant = QdrantAdapter()

        _index_service = IndexService(
            vault_path=vault_path,
            parser=parser,
            chunker=chunker,
            embedder=embedder,
            qdrant_adapter=qdrant,
            vault_file_map=vault_file_map,
        )
        _index_service.initialize()

    return _index_service


def set_index_service(service: IndexService) -> None:
    """Override the IndexService singleton (for testing)."""
    global _index_service  # noqa: PLW0603
    _index_service = service
