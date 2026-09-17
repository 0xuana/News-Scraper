"""Restartable historical pagination workflow."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from collector.aigupiao.parser import parse_payload
from collector.collectors.protocols import NewsClient, Repository

LOGGER = logging.getLogger(__name__)
COLLECTOR_NAME = "aigupiao_backfill"


class CursorNotAdvancing(RuntimeError):
    """Pagination returned the same or a newer boundary."""


@dataclass(frozen=True, slots=True)
class BackfillResult:
    total_processed: int
    oldest_news_id: int | None
    oldest_time: int | None


def run_backfill(
    client: NewsClient,
    repository: Repository,
    *,
    before: int | None = None,
    interval: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
) -> BackfillResult:
    cursor = before if before is not None else repository.get_cursor(COLLECTOR_NAME) or 0
    total = 0
    oldest_id: int | None = None
    oldest_time: int | None = None

    while True:
        started = time.monotonic()
        items = parse_payload(client.fetch(cursor))
        if not items:
            LOGGER.info("BACKFILL COMPLETE total_processed=%d oldest_time=%s", total, oldest_time)
            return BackfillResult(total, oldest_id, oldest_time)

        next_cursor = min(item.rec_time for item in items)
        if cursor != 0 and next_cursor >= cursor:
            raise CursorNotAdvancing(
                f"cursor did not advance: previous={cursor}, next={next_cursor}"
            )
        repository.save_batch(items, collector_name=COLLECTOR_NAME, cursor=next_cursor)
        oldest = min(items, key=lambda item: item.rec_time)
        oldest_id, oldest_time = oldest.id, oldest.rec_time
        total += len(items)
        LOGGER.info(
            "mode=backfill before=%d received=%d oldest_time=%d duration=%.2fs",
            cursor,
            len(items),
            next_cursor,
            time.monotonic() - started,
        )
        cursor = next_cursor
        sleep(interval)

