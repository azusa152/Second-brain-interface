import json
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from backend.logging_config import get_logger, setup_logging


def test_setup_logging_should_emit_json_when_json_output_enabled(capsys) -> None:
    # Arrange
    setup_logging(log_level="INFO", json_output=True)
    logger = get_logger("tests.logging")

    # Act
    logger.info("logging_json_event", component="tests")
    captured = capsys.readouterr()

    # Assert
    lines = [line for line in captured.out.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert payload["event"] == "logging_json_event"
    assert payload["component"] == "tests"
    assert payload["logger"] == "tests.logging"
    assert payload["level"] == "info"


def test_setup_logging_should_emit_console_when_json_output_disabled(capsys) -> None:
    # Arrange
    setup_logging(log_level="INFO", json_output=False)
    logger = get_logger("tests.logging")

    # Act
    logger.info("logging_console_event", component="tests")
    captured = capsys.readouterr()

    # Assert
    lines = [line for line in captured.out.splitlines() if line.strip()]
    rendered = lines[-1]
    assert "logging_console_event" in rendered
    assert "component" in rendered
    assert "tests" in rendered
    assert not rendered.lstrip().startswith("{")


def test_setup_logging_should_attach_file_handler_when_log_file_enabled(tmp_path: Path) -> None:
    # Arrange
    log_dir = str(tmp_path / "logs")

    # Act
    setup_logging(log_level="INFO", json_output=True, log_file_enabled=True, log_dir=log_dir)

    # Assert — a TimedRotatingFileHandler is present on the root logger
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(file_handlers) == 1, "Expected exactly one TimedRotatingFileHandler"
    handler = file_handlers[0]
    assert handler.when == "MIDNIGHT"
    assert handler.utc is True
    assert handler.backupCount == 3


def test_setup_logging_should_create_log_dir_when_missing(tmp_path: Path) -> None:
    # Arrange
    log_dir = str(tmp_path / "nested" / "logs")
    assert not os.path.exists(log_dir)

    # Act
    setup_logging(log_level="INFO", json_output=True, log_file_enabled=True, log_dir=log_dir)

    # Assert
    assert os.path.isdir(log_dir)


def test_setup_logging_should_write_json_to_log_file(tmp_path: Path) -> None:
    # Arrange
    log_dir = str(tmp_path / "logs")
    setup_logging(log_level="INFO", json_output=True, log_file_enabled=True, log_dir=log_dir)
    logger = get_logger("tests.file_logging")

    # Act
    logger.info("file_logging_event", component="tests")
    # Flush all file handlers to ensure the write is committed
    for handler in logging.getLogger().handlers:
        handler.flush()

    # Assert — log file exists and contains a valid JSON line for our event
    log_file = os.path.join(log_dir, "sbi.log")
    assert os.path.isfile(log_file)
    lines = Path(log_file).read_text(encoding="utf-8").splitlines()
    json_lines = [json.loads(line) for line in lines if line.strip()]
    events = [e for e in json_lines if e.get("event") == "file_logging_event"]
    assert events, "Expected at least one 'file_logging_event' in the log file"
    assert events[0]["component"] == "tests"
    assert events[0]["level"] == "info"


def test_setup_logging_should_not_attach_file_handler_when_disabled() -> None:
    # Arrange / Act
    setup_logging(log_level="INFO", json_output=True, log_file_enabled=False)

    # Assert — no TimedRotatingFileHandler on the root logger
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(file_handlers) == 0, "Expected no file handlers when log_file_enabled=False"
