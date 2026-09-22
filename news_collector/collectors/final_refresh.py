"""Final refresh and freezing of news after its mutable month."""

from __future__ import annotations

import calendar
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from news_collector.collectors.backfill import CursorNotAdvancing
from news_collector.collectors.protocols import NewsClient, Repository
from news_collector.collectors.request import fetch_page

LOGGER = logging.getLogger(__name__)
COLLECTOR_NAME = "aigupiao_final_refresh"


@dataclass(frozen=True, slots=True)
class FinalRefreshResult:
    refreshed: int
    finalized: int
    cutoff: datetime


def one_month_ago(value: datetime) -> datetime:
    """Subtract one calendar month while keeping the closest valid day."""
    year = value.year if value.month > 1 else value.year - 1
    month = value.month - 1 if value.month > 1 else 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def run_final_refresh(
    client: NewsClient,
    repository: Repository,
    *,
    interval: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FinalRefreshResult:
    """Refresh through the one-month boundary, then freeze all due records."""
    started_at = now()
    cutoff = one_month_ago(started_at)
    cutoff_timestamp = int(cutoff.timestamp())
    cursor = 0
    refreshed = 0

    while True:
        page = fetch_page(client, before=cursor, collector_name=COLLECTOR_NAME)
        items = page.items
        if not items:
            finalized = repository.finalize_due()
            repository.save_batch(
                [],
                collector_name=COLLECTOR_NAME,
                cursor=int(started_at.timestamp()),
                request_coverage=page.coverage,
            )
            return FinalRefreshResult(refreshed, finalized, cutoff)

        next_cursor = min(item.rec_time for item in items)
        if cursor != 0 and next_cursor >= cursor:
            raise CursorNotAdvancing(
                f"final-refresh cursor did not advance: previous={cursor}, next={next_cursor}"
            )
        repository.save_batch(items, request_coverage=page.coverage)
        refreshed += len(items)
        LOGGER.info(
            "mode=final_refresh before=%d received=%d oldest_time=%d cutoff=%d",
            cursor,
            len(items),
            next_cursor,
            cutoff_timestamp,
        )
        if next_cursor <= cutoff_timestamp:
            finalized = repository.finalize_due()
            repository.save_batch(
                [], collector_name=COLLECTOR_NAME, cursor=int(started_at.timestamp())
            )
            LOGGER.info(
                "FINAL REFRESH COMPLETE refreshed=%d finalized=%d", refreshed, finalized
            )
            return FinalRefreshResult(refreshed, finalized, cutoff)
        cursor = next_cursor
        sleep(interval)
