import os

from backend.application.index_service import IndexService
from backend.application.search_service import SearchService
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.event_log import EventLog
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.qdrant_adapter import QdrantAdapter
from backend.infrastructure.vault_file_map import VaultFileMap
from backend.logging_config import get_logger

logger = get_logger(__name__)

_index_service: IndexService | None = None
_search_service: SearchService | None = None

# Shared infrastructure singletons (created once, shared across services)
_embedder: EmbeddingService | None = None
_qdrant: QdrantAdapter | None = None
_event_log: EventLog | None = None


def initialize_services() -> None:
    """Initialize all services at startup. Called from FastAPI lifespan."""
    get_index_service()
    get_search_service()


def get_index_service() -> IndexService:
    """Return the singleton IndexService, creating it on first call."""
    global _index_service, _embedder, _qdrant, _event_log  # noqa: PLW0603
    if _index_service is None:
        vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "/vault")
        logger.info("Initializing IndexService with vault: %s", vault_path)

        vault_file_map = VaultFileMap(vault_path)
        parser = MarkdownParser(vault_file_map)
        chunker = Chunker()
        _embedder = _embedder or EmbeddingService()
        _qdrant = _qdrant or QdrantAdapter()
        _event_log = _event_log or EventLog()

        _index_service = IndexService(
            vault_path=vault_path,
            parser=parser,
            chunker=chunker,
            embedder=_embedder,
            qdrant_adapter=_qdrant,
            vault_file_map=vault_file_map,
            event_log=_event_log,
        )
        _index_service.initialize()

    return _index_service


def get_search_service() -> SearchService:
    """Return the singleton SearchService, creating it on first call."""
    global _search_service, _embedder, _qdrant  # noqa: PLW0603
    if _search_service is None:
        _embedder = _embedder or EmbeddingService()
        _qdrant = _qdrant or QdrantAdapter()

        _search_service = SearchService(
            embedder=_embedder,
            qdrant_adapter=_qdrant,
        )
        logger.info("Initialized SearchService")

    return _search_service


def set_index_service(service: IndexService) -> None:
    """Override the IndexService singleton (for testing)."""
    global _index_service  # noqa: PLW0603
    _index_service = service


def set_search_service(service: SearchService) -> None:
    """Override the SearchService singleton (for testing)."""
    global _search_service  # noqa: PLW0603
    _search_service = service
