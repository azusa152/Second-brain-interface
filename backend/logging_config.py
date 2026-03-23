import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

import structlog

_NOISY_LOGGERS: tuple[str, ...] = (
    "uvicorn.access",
    "watchdog",
    "qdrant_client",
    "fastembed",
    "httpx",
)

_LOG_FILENAME = "sbi.log"


def setup_logging(
    log_level: str = "INFO",
    json_output: bool = True,
    log_file_enabled: bool = False,
    log_dir: str = "./logs",
) -> None:
    """Configure application logging with structlog and stdlib compatibility.

    Attaches a stdout handler (format controlled by ``json_output``) and,
    when ``log_file_enabled`` is ``True``, a second handler that writes
    newline-delimited JSON to ``<log_dir>/sbi.log``.  The file handler rotates
    daily at UTC midnight and retains the last 3 days of history.
    """
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

    stdout_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(stdout_formatter)

    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
    root.handlers.clear()
    root.addHandler(stdout_handler)

    if log_file_enabled:
        root.addHandler(_build_file_handler(log_dir, shared_processors))

    root.setLevel(parsed_level)

    for logger_name in _NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _build_file_handler(
    log_dir: str,
    shared_processors: list[structlog.types.Processor],
) -> TimedRotatingFileHandler:
    """Create a daily-rotating file handler that always writes JSON.

    Rotates at UTC midnight, keeps 3 days of history (backupCount=3).
    Rotated files are named with the default ``%Y-%m-%d`` suffix, e.g.
    ``sbi.log.2026-03-22``.
    """
    os.makedirs(log_dir, exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, _LOG_FILENAME),
        when="midnight",
        utc=True,
        backupCount=3,
        encoding="utf-8",
    )

    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    file_handler.setFormatter(file_formatter)
    return file_handler


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named logger. Use as: logger = get_logger(__name__)."""
    return structlog.get_logger(name)


def _to_logging_level(level: str) -> int:
    """Convert log level name to logging module level."""
    parsed = logging.getLevelName(level.upper())
    return parsed if isinstance(parsed, int) else logging.INFO
