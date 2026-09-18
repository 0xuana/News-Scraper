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


def test_scheduled_configuration_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/news")
    monkeypatch.delenv("INITIAL_BACKFILL_DAYS", raising=False)
    monkeypatch.delenv("SYNC_INTERVAL", raising=False)
    monkeypatch.delenv("SYNC_OVERLAP_SECONDS", raising=False)
    monkeypatch.setattr("collector.config.load_dotenv", lambda: None)

    settings = Settings.from_env()

    assert settings.initial_backfill_days == 60
    assert settings.sync_interval == 3600.0
    assert settings.sync_overlap_seconds == 300


def test_scheduled_configuration_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/news")
    monkeypatch.setenv("INITIAL_BACKFILL_DAYS", "30")
    monkeypatch.setenv("SYNC_INTERVAL", "1800")
    monkeypatch.setenv("SYNC_OVERLAP_SECONDS", "120")
    monkeypatch.setattr("collector.config.load_dotenv", lambda: None)

    settings = Settings.from_env()

    assert settings.initial_backfill_days == 30
    assert settings.sync_interval == 1800.0
    assert settings.sync_overlap_seconds == 120
