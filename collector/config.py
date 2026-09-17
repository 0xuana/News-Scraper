"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://apis.aigupiao.com/Express/express_list/"


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _non_negative_int(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    base_url: str = DEFAULT_BASE_URL
    request_interval: float = 3.0
    live_interval: float = 45.0
    http_timeout: float = 15.0
    max_retries: int = 5
    max_backoff: float = 60.0

    @classmethod
    def from_env(cls, *, require_database: bool = True) -> Settings:
        load_dotenv()
        database_url = os.getenv("DATABASE_URL", "")
        if require_database and not database_url:
            raise ValueError("DATABASE_URL is required")
        return cls(
            database_url=database_url,
            base_url=os.getenv("AIGUPIAO_BASE_URL", DEFAULT_BASE_URL),
            request_interval=_positive_float("AIGUPIAO_REQUEST_INTERVAL", 3.0),
            live_interval=_positive_float("LIVE_INTERVAL", 45.0),
            http_timeout=_positive_float("HTTP_TIMEOUT", 15.0),
            max_retries=_non_negative_int("MAX_RETRIES", 5),
            max_backoff=_positive_float("MAX_BACKOFF", 60.0),
        )
