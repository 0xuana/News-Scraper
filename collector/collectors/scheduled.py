"""Restart-safe initial and periodic news synchronization."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from collector.aigupiao.parser import parse_payload
from collector.collectors.backfill import CursorNotAdvancing
from collector.collectors.protocols import NewsClient, Repository

LOGGER = logging.getLogger(__name__)
COLLECTOR_NAME = "aigupiao_scheduled"
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True, slots=True)
class ScheduledCycleResult:
    mode: str
    window_start: int
    received: int
    stored: int


def run_scheduled_cycle(
    client: NewsClient,
    repository: Repository,
    *,
    now: int,
    initial_backfill_days: int,
    overlap_seconds: int,
    request_interval: float,
    sleep: Callable[[float], None] = time.sleep,
) -> ScheduledCycleResult:
    """Synchronize one complete time window, then atomically advance its checkpoint."""
    checkpoint = repository.get_cursor(COLLECTOR_NAME)
    if checkpoint is None:
        mode = "initial"
        window_start = now - initial_backfill_days * SECONDS_PER_DAY
    else:
        mode = "incremental"
        window_start = max(0, checkpoint - overlap_seconds)

    cursor = 0
    received = 0
    stored = 0
    while True:
        items = parse_payload(client.fetch(cursor))
        if not items:
            break

        received += len(items)
        next_cursor = min(item.rec_time for item in items)
        if cursor != 0 and next_cursor >= cursor:
            raise CursorNotAdvancing(
                f"cursor did not advance: previous={cursor}, next={next_cursor}"
            )

        selected = [item for item in items if item.rec_time >= window_start]
        if selected:
            repository.save_batch(selected)
            stored += len(selected)

        if next_cursor <= window_start:
            break
        cursor = next_cursor
        sleep(request_interval)

    repository.save_batch([], collector_name=COLLECTOR_NAME, cursor=now)
    return ScheduledCycleResult(mode, window_start, received, stored)


def run_scheduled(
    client: NewsClient,
    repository: Repository,
    *,
    initial_backfill_days: int = 60,
    sync_interval: float = 3_600.0,
    overlap_seconds: int = 300,
    request_interval: float = 3.0,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run the initial history load and all subsequent periodic sync cycles."""
    while True:
        started = time.monotonic()
        result = run_scheduled_cycle(
            client,
            repository,
            now=int(clock()),
            initial_backfill_days=initial_backfill_days,
            overlap_seconds=overlap_seconds,
            request_interval=request_interval,
            sleep=sleep,
        )
        LOGGER.info(
            "mode=scheduled phase=%s window_start=%d received=%d stored=%d "
            "duration=%.2fs next_sync_in=%.1fs",
            result.mode,
            result.window_start,
            result.received,
            result.stored,
            time.monotonic() - started,
            sync_interval,
        )
        sleep(sync_interval)
