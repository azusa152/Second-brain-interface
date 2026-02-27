"""Service factory functions used as FastAPI dependencies.

Each ``get_*()`` function returns a cached singleton and is safe to pass
directly to ``Depends()``.  In tests, override via
``app.dependency_overrides[get_search_service] = lambda: mock``.
"""

from backend.application.augment_service import AugmentService
from backend.application.index_service import IndexService
from backend.application.intent_service import IntentService
from backend.application.search_service import SearchService
from backend.config import get_settings
from backend.domain.constants import INTENT_DEFAULT_DOMAIN_ANCHORS, INTENT_DEFAULT_KEYWORDS
from backend.infrastructure.chunker import Chunker
from backend.infrastructure.embedding import EmbeddingService
from backend.infrastructure.event_log import EventLog
from backend.infrastructure.hash_registry import HashRegistry
from backend.infrastructure.markdown_parser import MarkdownParser
from backend.infrastructure.qdrant_adapter import QdrantAdapter
from backend.infrastructure.scheduler import Scheduler
from backend.infrastructure.vault_file_map import VaultFileMap
from backend.logging_config import get_logger

logger = get_logger(__name__)

_index_service: IndexService | None = None
_search_service: SearchService | None = None
_intent_service: IntentService | None = None
_augment_service: AugmentService | None = None
_scheduler: Scheduler | None = None
_scheduler_disabled: bool = False  # Memoized when SCHEDULED_REBUILD_ENABLED=false

# Shared infrastructure singletons (created once, shared across services)
_embedder: EmbeddingService | None = None
_qdrant: QdrantAdapter | None = None
_event_log: EventLog | None = None


def initialize_services() -> None:
    """Initialize all services at startup. Called from FastAPI lifespan."""
    get_index_service()
    get_search_service()
    get_scheduler()
    intent_service = get_intent_service()
    intent_service.warm_up()
    get_augment_service()


def get_index_service() -> IndexService:
    """Return the singleton IndexService, creating it on first call."""
    global _index_service, _embedder, _qdrant, _event_log  # noqa: PLW0603
    if _index_service is None:
        settings = get_settings()
        vault_path = settings.obsidian_vault_path
        use_polling = settings.use_polling_observer
        polling_interval = settings.polling_interval_seconds
        logger.info(
            "Initializing IndexService with vault: %s (polling=%s, interval=%.1fs)",
            vault_path,
            use_polling,
            polling_interval,
        )

        vault_file_map = VaultFileMap(vault_path)
        parser = MarkdownParser(vault_file_map)
        chunker = Chunker()
        _embedder = _embedder or EmbeddingService()
        _qdrant = _qdrant or QdrantAdapter()
        _event_log = _event_log or EventLog()
        hash_registry = HashRegistry(settings.hash_registry_data_path)

        _index_service = IndexService(
            vault_path=vault_path,
            parser=parser,
            chunker=chunker,
            embedder=_embedder,
            qdrant_adapter=_qdrant,
            vault_file_map=vault_file_map,
            event_log=_event_log,
            use_polling=use_polling,
            polling_interval=polling_interval,
            hash_registry=hash_registry,
        )
        _index_service.initialize()

    return _index_service


def get_scheduler() -> Scheduler | None:
    """Return the singleton Scheduler if scheduling is enabled, or None.

    The disabled state is memoized so the env var is only read once per process,
    consistent with how all other get_*() singletons behave.
    """
    global _scheduler, _scheduler_disabled  # noqa: PLW0603
    if _scheduler_disabled:
        return None
    if _scheduler is None:
        settings = get_settings()
        if not settings.scheduled_rebuild_enabled:
            logger.info("Scheduled rebuild disabled (SCHEDULED_REBUILD_ENABLED=false)")
            _scheduler_disabled = True
            return None

        index_service = get_index_service()
        _scheduler = Scheduler(
            cron_hour=settings.rebuild_cron_hour,
            cron_minute=settings.rebuild_cron_minute,
            job_fn=index_service.incremental_rebuild,
        )

    return _scheduler


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


def get_augment_service() -> AugmentService:
    """Return the singleton AugmentService, creating it on first call."""
    global _augment_service  # noqa: PLW0603
    if _augment_service is None:
        _augment_service = AugmentService(
            intent_service=get_intent_service(),
            search_service=get_search_service(),
        )
        logger.info("Initialized AugmentService")

    return _augment_service


def get_intent_service() -> IntentService:
    """Return the singleton IntentService, creating it on first call."""
    global _intent_service, _embedder  # noqa: PLW0603
    if _intent_service is None:
        _embedder = _embedder or EmbeddingService()

        keywords_env = get_settings().intent_personal_keywords
        keywords = (
            [kw.strip() for kw in keywords_env.split(",") if kw.strip()]
            if keywords_env
            else list(INTENT_DEFAULT_KEYWORDS)
        )

        _intent_service = IntentService(
            embedder=_embedder,
            keywords=keywords,
            domain_anchors=list(INTENT_DEFAULT_DOMAIN_ANCHORS),
        )
        logger.info("Initialized IntentService with %d keywords", len(keywords))

    return _intent_service


def set_scheduler(scheduler: Scheduler | None) -> None:
    """Override the Scheduler singleton (for testing). Also resets the disabled flag."""
    global _scheduler, _scheduler_disabled  # noqa: PLW0603
    _scheduler = scheduler
    _scheduler_disabled = False
