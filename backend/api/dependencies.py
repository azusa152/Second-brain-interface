import os

from backend.application.augment_service import AugmentService
from backend.application.index_service import IndexService
from backend.application.intent_service import IntentService
from backend.application.search_service import SearchService
from backend.domain.constants import (
    INTENT_DEFAULT_DOMAIN_ANCHORS,
    INTENT_DEFAULT_KEYWORDS,
    POLLING_INTERVAL_SECONDS,
    REBUILD_CRON_HOUR,
    REBUILD_CRON_MINUTE,
)
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


def _parse_watcher_config() -> tuple[bool, float]:
    """Read USE_POLLING_OBSERVER and POLLING_INTERVAL_SECONDS from the environment.

    Returns (use_polling, polling_interval). Falls back to safe defaults and logs a
    warning when the numeric interval value cannot be parsed.
    """
    use_polling = os.getenv("USE_POLLING_OBSERVER", "false").lower() == "true"
    try:
        polling_interval = float(
            os.getenv("POLLING_INTERVAL_SECONDS", str(POLLING_INTERVAL_SECONDS))
        )
    except ValueError:
        logger.warning(
            "Invalid POLLING_INTERVAL_SECONDS env var; using default %.1fs",
            POLLING_INTERVAL_SECONDS,
        )
        polling_interval = POLLING_INTERVAL_SECONDS
    return use_polling, polling_interval


def get_index_service() -> IndexService:
    """Return the singleton IndexService, creating it on first call."""
    global _index_service, _embedder, _qdrant, _event_log  # noqa: PLW0603
    if _index_service is None:
        vault_path = os.getenv("OBSIDIAN_VAULT_PATH", "/vault")
        use_polling, polling_interval = _parse_watcher_config()
        logger.info(
            "Initializing IndexService with vault: %s (polling=%s, interval=%.1fs)",
            vault_path,
            use_polling,
            polling_interval,
        )

        data_path = os.getenv("HASH_REGISTRY_DATA_PATH", "/data")
        vault_file_map = VaultFileMap(vault_path)
        parser = MarkdownParser(vault_file_map)
        chunker = Chunker()
        _embedder = _embedder or EmbeddingService()
        _qdrant = _qdrant or QdrantAdapter()
        _event_log = _event_log or EventLog()
        hash_registry = HashRegistry(data_path)

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
        enabled = os.getenv("SCHEDULED_REBUILD_ENABLED", "true").lower() == "true"
        if not enabled:
            logger.info("Scheduled rebuild disabled (SCHEDULED_REBUILD_ENABLED=false)")
            _scheduler_disabled = True
            return None

        try:
            cron_hour = int(os.getenv("REBUILD_CRON_HOUR", str(REBUILD_CRON_HOUR)))
            cron_minute = int(os.getenv("REBUILD_CRON_MINUTE", str(REBUILD_CRON_MINUTE)))
        except ValueError:
            logger.warning(
                "Invalid REBUILD_CRON_HOUR/MINUTE env vars; using defaults %02d:%02d",
                REBUILD_CRON_HOUR,
                REBUILD_CRON_MINUTE,
            )
            cron_hour = REBUILD_CRON_HOUR
            cron_minute = REBUILD_CRON_MINUTE

        index_service = get_index_service()
        _scheduler = Scheduler(
            cron_hour=cron_hour,
            cron_minute=cron_minute,
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

        # Allow per-deployment keyword overrides via comma-separated env var
        keywords_env = os.getenv("INTENT_PERSONAL_KEYWORDS", "")
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


def set_augment_service(service: AugmentService) -> None:
    """Override the AugmentService singleton (for testing)."""
    global _augment_service  # noqa: PLW0603
    _augment_service = service


def set_index_service(service: IndexService) -> None:
    """Override the IndexService singleton (for testing)."""
    global _index_service  # noqa: PLW0603
    _index_service = service


def set_search_service(service: SearchService) -> None:
    """Override the SearchService singleton (for testing)."""
    global _search_service  # noqa: PLW0603
    _search_service = service


def set_intent_service(service: IntentService) -> None:
    """Override the IntentService singleton (for testing)."""
    global _intent_service  # noqa: PLW0603
    _intent_service = service


def set_scheduler(scheduler: Scheduler | None) -> None:
    """Override the Scheduler singleton (for testing). Also resets the disabled flag."""
    global _scheduler, _scheduler_disabled  # noqa: PLW0603
    _scheduler = scheduler
    _scheduler_disabled = False
