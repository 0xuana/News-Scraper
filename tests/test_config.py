import pytest

from collector.config import Settings


def test_database_url_is_required_for_collectors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("collector.config.load_dotenv", lambda: None)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings.from_env()


def test_probe_configuration_does_not_require_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("collector.config.load_dotenv", lambda: None)

    assert Settings.from_env(require_database=False).database_url == ""
