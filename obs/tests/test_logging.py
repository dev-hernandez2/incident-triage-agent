import json
import logging

from obs.logging import configure_logging


def test_configure_logging_emits_json(capsys: object) -> None:
    logger = configure_logging("test-service")
    logger.info("hello", extra={"incident_id": "abc"})

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)

    assert payload["level"] == "INFO"
    assert payload["message"] == "hello"
    assert payload["logger"] == "test-service"
    assert payload["incident_id"] == "abc"


def test_configure_logging_replaces_handlers_on_reconfigure() -> None:
    logger = configure_logging("reconfigure-test")
    configure_logging("reconfigure-test")

    assert len(logger.handlers) == 1
    assert logger.propagate is False
    assert logger.level == logging.INFO
