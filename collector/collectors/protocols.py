"""Narrow interfaces used by collector workflows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from collector.models import NewsItem


class NewsClient(Protocol):
    def fetch(self, before: int = 0) -> dict[str, Any]: ...


class Repository(Protocol):
    def get_cursor(self, collector_name: str) -> int | None: ...

    def save_batch(
        self,
        items: Sequence[NewsItem],
        *,
        collector_name: str | None = None,
        cursor: int | None = None,
    ) -> None: ...

    def finalize_due(self) -> int: ...
