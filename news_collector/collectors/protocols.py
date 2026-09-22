"""Narrow interfaces used by collector workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from news_collector.models import NewsItem, RequestCoverage


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
        checkpoints: Mapping[str, int] | None = None,
        request_coverage: RequestCoverage | None = None,
    ) -> None: ...

    def find_coverage_gaps(self, window_start: int, window_end: int) -> list[tuple[int, int]]: ...

    def finalize_due(self) -> int: ...
