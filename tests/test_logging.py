import json
import logging

from app.core.logging import JsonFormatter, redact_secrets


def test_redact_secrets_recursively() -> None:
    source = {
        "provider": "hetzner",
        "api_token": "abc",
        "nested": {"password": "def", "safe": "visible"},
        "headers": {"Authorization": "Bearer secret"},
    }

    redacted = redact_secrets(source)

    assert redacted["provider"] == "hetzner"
    assert redacted["api_token"] == "***REDACTED***"
    assert redacted["nested"]["password"] == "***REDACTED***"
    assert redacted["nested"]["safe"] == "visible"
    assert redacted["headers"]["Authorization"] == "***REDACTED***"


def test_json_formatter_redacts_secret_extra_fields() -> None:
    record = logging.LogRecord(
        name="aso.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event",
        args=(),
        exc_info=None,
    )
    record.api_token = "should-never-appear"
    record.node_id = 7

    payload = json.loads(JsonFormatter().format(record))

    assert payload["api_token"] == "***REDACTED***"
    assert payload["node_id"] == 7
    assert "should-never-appear" not in json.dumps(payload)
