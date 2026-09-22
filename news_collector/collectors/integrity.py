"""Detect and repair gaps in audited API request coverage."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from news_collector.collectors.backfill import CursorNotAdvancing
from news_collector.collectors.protocols import NewsClient, Repository
from news_collector.collectors.request import fetch_page

LOGGER = logging.getLogger(__name__)
COLLECTOR_NAME = "aigupiao_coverage_repair"
CHECKPOINT_NAME = "aigupiao_coverage_check"
SECONDS_PER_DAY = 86_400


class CoverageIncomplete(RuntimeError):
    """The audited request intervals still contain gaps after repair."""


@dataclass(frozen=True, slots=True)
class CoverageCheckResult:
    window_start: int
    window_end: int
    gaps_found: int
    requests_made: int
    news_received: int


def run_coverage_check(
    client: NewsClient,
    repository: Repository,
    *,
    now: int,
    initial_backfill_days: int,
    request_interval: float,
    sleep: Callable[[float], None] = time.sleep,
) -> CoverageCheckResult:
    """Repair every audited request-coverage gap in the rolling window."""
    window_start = now - initial_backfill_days * SECONDS_PER_DAY
    gaps = repository.find_coverage_gaps(window_start, now)
    requests_made = 0
    news_received = 0

    for gap_start, gap_end in reversed(gaps):
        LOGGER.warning(
            "mode=coverage_check gap_start=%d gap_end=%d action=repair",
            gap_start,
            gap_end,
        )
        cursor = gap_end
        while cursor > gap_start:
            page = fetch_page(client, before=cursor, collector_name=COLLECTOR_NAME)
            requests_made += 1
            items = page.items
            repository.save_batch(items, request_coverage=page.coverage)
            if not items:
                LOGGER.warning(
                    "mode=coverage_check gap_start=%d gap_end=%d before=%d "
                    "result=empty",
                    gap_start,
                    gap_end,
                    cursor,
                )
                break
            news_received += len(items)
            next_cursor = min(item.rec_time for item in items)
            if next_cursor >= cursor:
                raise CursorNotAdvancing(
                    "coverage repair cursor did not advance: "
                    f"previous={cursor}, next={next_cursor}"
                )
            if next_cursor <= gap_start:
                break
            cursor = next_cursor
            sleep(request_interval)

    remaining = repository.find_coverage_gaps(window_start, now)
    if remaining:
        for gap_start, gap_end in remaining:
            LOGGER.warning(
                "mode=coverage_check gap_start=%d gap_end=%d result=unresolved",
                gap_start,
                gap_end,
            )
        raise CoverageIncomplete(f"{len(remaining)} request-coverage gap(s) remain")

    repository.save_batch([], collector_name=CHECKPOINT_NAME, cursor=now)
    LOGGER.info(
        "mode=coverage_check result=complete window_start=%d window_end=%d "
        "gaps_found=%d requests=%d received=%d",
        window_start,
        now,
        len(gaps),
        requests_made,
        news_received,
    )
    return CoverageCheckResult(
        window_start, now, len(gaps), requests_made, news_received
    )
