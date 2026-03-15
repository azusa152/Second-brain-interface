import logging
import sys

import structlog

_NOISY_LOGGERS: tuple[str, ...] = (
    "uvicorn.access",
    "watchdog",
    "qdrant_client",
    "fastembed",
    "httpx",
)


def setup_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure application logging with structlog and stdlib compatibility."""
    parsed_level = _to_logging_level(log_level)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    renderer: structlog.types.Processor
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(parsed_level)

    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named logger. Use as: logger = get_logger(__name__)."""
    return structlog.get_logger(name)


def _to_logging_level(level: str) -> int:
    """Convert log level name to logging module level."""
    parsed = logging.getLevelName(level.upper())
    return parsed if isinstance(parsed, int) else logging.INFO
