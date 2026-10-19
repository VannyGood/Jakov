import json
import logging
from pathlib import Path

from jakov.logging_setup import REDACTED, SecretRedactor, get_logger, setup_logging
from tests.conftest import TOKEN


def test_redacts_known_secrets_and_token_shapes() -> None:
    r = SecretRedactor(["my-api-key-123"])
    text = r.redact(f"url=https://api.telegram.org/bot{TOKEN}/getMe key=my-api-key-123")
    assert TOKEN not in text and "my-api-key-123" not in text
    assert text.count(REDACTED) == 2


def test_short_values_are_not_treated_as_secrets() -> None:
    assert SecretRedactor(["abc"]).redact("abc") == "abc"


def test_log_file_never_contains_secrets(tmp_path: Path) -> None:
    setup_logging(tmp_path, "INFO", secrets=["vt-secret-key-999"])
    get_logger("t").info("calling", url=f"https://x/{TOKEN}", key="vt-secret-key-999")
    logging.getLogger("plain").warning("token %s", TOKEN)
    for h in logging.getLogger().handlers:
        h.flush()
    content = (tmp_path / "jakov.log").read_text()
    assert TOKEN not in content and "vt-secret-key-999" not in content
    events = [json.loads(line)["event"] for line in content.splitlines()]
    assert "calling" in events
    logging.getLogger().handlers.clear()
