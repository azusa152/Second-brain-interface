import json

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
