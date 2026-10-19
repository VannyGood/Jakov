import pytest
from pydantic import ValidationError

from jakov.config import Settings
from tests.conftest import TOKEN


def make(**overrides: object) -> Settings:
    values: dict[str, object] = {"bot_token": TOKEN, "admin_ids": "1", "timezone": "UTC"}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_admin_ids_accepts_comma_list() -> None:
    assert make(admin_ids="1, 2,3").admin_ids == [1, 2, 3]
    assert make(admin_ids=7).admin_ids == [7]


def test_primary_owner_is_first_admin() -> None:
    assert make(admin_ids="9,1").primary_owner_id == 9


def test_rejects_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="Unknown timezone"):
        make(timezone="Mars/Olympus")


def test_requires_at_least_one_admin() -> None:
    with pytest.raises(ValidationError):
        make(admin_ids="")


def test_webhook_mode_needs_url() -> None:
    with pytest.raises(ValidationError, match="WEBHOOK_BASE_URL"):
        make(run_mode="webhook")


def test_empty_api_keys_become_none_and_secrets_hidden() -> None:
    s = make(virustotal_api_key="", anthropic_api_key="sk-secret-value")
    assert s.virustotal_api_key is None
    assert "sk-secret-value" not in repr(s)
    assert TOKEN not in repr(s)
    assert set(s.secret_values()) == {TOKEN, "sk-secret-value"}
