"""Create auditable page results for successful API requests."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from news_collector.aigupiao.parser import parse_payload
from news_collector.collectors.protocols import NewsClient
from news_collector.models import NewsItem, RequestCoverage


@dataclass(frozen=True, slots=True)
class FetchedPage:
    items: list[NewsItem]
    coverage: RequestCoverage


def fetch_page(
    client: NewsClient,
    *,
    before: int,
    collector_name: str,
    clock: Callable[[], float] = time.time,
) -> FetchedPage:
    """Fetch and parse one page, assigning its request UUID and time interval."""
    requested_at = int(clock())
    items = parse_payload(client.fetch(before))
    coverage_end = before or requested_at
    coverage_start = min((item.rec_time for item in items), default=coverage_end)
    return FetchedPage(
        items,
        RequestCoverage(
            request_id=uuid4(),
            collector_name=collector_name,
            requested_before=before,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            news_ids=tuple(item.id for item in items),
            requested_at=requested_at,
        ),
    )
