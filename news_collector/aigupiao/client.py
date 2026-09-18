"""Conservative synchronous HTTP client for Aigupiao."""

from __future__ import annotations

import email.utils
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class AigupiaoError(RuntimeError):
    """Base API client error."""


class AccessDenied(AigupiaoError):
    """The server explicitly refused access."""


class RetriesExhausted(AigupiaoError):
    """All attempts failed with a temporary error."""


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


class AigupiaoClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        max_retries: int = 5,
        max_backoff: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            trust_env=False,
        )
        self._base_url = base_url
        self._max_retries = max_retries
        self._max_backoff = max_backoff
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AigupiaoClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, before: int = 0) -> dict[str, Any]:
        params = {
            "before": before,
            "source": "pc",
            "web_data": "yes",
            "number": 20,
            "division": "",
            "express_show_type": 0,
        }
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            response: httpx.Response | None = None
            try:
                response = self._client.get(self._base_url, params=params)
                if response.status_code == 403:
                    raise AccessDenied("Aigupiao returned HTTP 403; collection stopped")
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("rslt") != "succ":
                    raise AigupiaoError("Aigupiao returned an unsuccessful payload")
                return payload
            except AccessDenied:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError,
                    ValueError, AigupiaoError) as error:
                last_error = error
                if attempt >= self._max_retries:
                    break
                server_delay = (
                    _retry_after(response.headers.get("Retry-After")) if response else None
                )
                delay = min(self._max_backoff, server_delay or 5 * (2**attempt))
                LOGGER.warning(
                    "request_retry status=%s retry_in=%.1fs attempt=%d",
                    response.status_code if response else None,
                    delay,
                    attempt + 1,
                )
                self._sleep(delay)
        raise RetriesExhausted("Aigupiao request retries exhausted") from last_error
