"""Restart-safe recent and rolling-history news synchronization."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from news_collector.aigupiao.parser import parse_payload
from news_collector.collectors.backfill import CursorNotAdvancing
from news_collector.collectors.final_refresh import (
    COLLECTOR_NAME as FINAL_REFRESH_COLLECTOR_NAME,
)
from news_collector.collectors.final_refresh import run_final_refresh
from news_collector.collectors.protocols import NewsClient, Repository

LOGGER = logging.getLogger(__name__)
COLLECTOR_NAME = "aigupiao_scheduled"
HISTORY_PROGRESS_NAME = "aigupiao_scheduled_history_progress"
HISTORY_COVERAGE_NAME = "aigupiao_scheduled_history_coverage"
HISTORY_EMPTY_COUNT_NAME = "aigupiao_scheduled_history_empty_count"
SECONDS_PER_DAY = 86_400
EMPTY_PROBE_LIMIT = 10
EMPTY_PROBE_STEP_SECONDS = 600


@dataclass(frozen=True, slots=True)
class ScheduledCycleResult:
    mode: str
    window_start: int
    received: int
    stored: int


def _next_cursor(items: list, cursor: int) -> int:
    next_cursor = min(item.rec_time for item in items)
    if cursor != 0 and next_cursor >= cursor:
        raise CursorNotAdvancing(
            f"cursor did not advance: previous={cursor}, next={next_cursor}"
        )
    return next_cursor


def _sync_recent(
    client: NewsClient,
    repository: Repository,
    *,
    now: int,
    overlap_seconds: int,
    request_interval: float,
    sleep: Callable[[float], None],
) -> tuple[str, int, int]:
    """Catch up current news before historical recovery."""
    checkpoint = repository.get_cursor(COLLECTOR_NAME)
    mode = "initial" if checkpoint is None else "incremental"
    target = None if checkpoint is None else max(0, checkpoint - overlap_seconds)
    cursor = 0
    received = 0
    stored = 0

    while True:
        items = parse_payload(client.fetch(cursor))
        if not items:
            break
        received += len(items)
        next_cursor = _next_cursor(items, cursor)
        selected = items if target is None else [item for item in items if item.rec_time >= target]
        if selected:
            repository.save_batch(selected)
            stored += len(selected)
        if target is None or next_cursor <= target:
            break
        cursor = next_cursor
        sleep(request_interval)

    repository.save_batch([], collector_name=COLLECTOR_NAME, cursor=now)
    return mode, received, stored


def _extend_history(
    client: NewsClient,
    repository: Repository,
    *,
    window_start: int,
    now: int,
    request_interval: float,
    sleep: Callable[[float], None],
) -> tuple[int, int]:
    """Resume the oldest committed page until the rolling boundary is covered."""
    coverage = repository.get_cursor(HISTORY_COVERAGE_NAME)
    if coverage is not None and coverage <= window_start:
        return 0, 0

    progress = repository.get_cursor(HISTORY_PROGRESS_NAME)
    empty_count = repository.get_cursor(HISTORY_EMPTY_COUNT_NAME) or 0
    cursor = progress or 0
    received = 0
    stored = 0

    while True:
        items = parse_payload(client.fetch(cursor))
        if not items:
            empty_count += 1
            probe_cursor = max(0, (cursor or now) - EMPTY_PROBE_STEP_SECONDS)
            checkpoints = {
                HISTORY_PROGRESS_NAME: probe_cursor,
                HISTORY_EMPTY_COUNT_NAME: empty_count,
            }
            if empty_count >= EMPTY_PROBE_LIMIT:
                checkpoints[HISTORY_COVERAGE_NAME] = window_start
            repository.save_batch([], checkpoints=checkpoints)
            cursor = probe_cursor
            if empty_count >= EMPTY_PROBE_LIMIT:
                return received, stored
            sleep(request_interval)
            continue

        received += len(items)
        empty_count = 0
        next_cursor = _next_cursor(items, cursor)
        selected = [item for item in items if item.rec_time >= window_start]
        checkpoints = {
            HISTORY_PROGRESS_NAME: next_cursor,
            HISTORY_EMPTY_COUNT_NAME: 0,
        }
        if next_cursor <= window_start:
            checkpoints[HISTORY_COVERAGE_NAME] = window_start
        repository.save_batch(selected, checkpoints=checkpoints)
        stored += len(selected)
        if next_cursor <= window_start:
            return received, stored
        cursor = next_cursor
        sleep(request_interval)


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
    """Catch up recent news, then establish or extend rolling-history coverage."""
    window_start = now - initial_backfill_days * SECONDS_PER_DAY
    mode, recent_received, recent_stored = _sync_recent(
        client,
        repository,
        now=now,
        overlap_seconds=overlap_seconds,
        request_interval=request_interval,
        sleep=sleep,
    )
    history_received, history_stored = _extend_history(
        client,
        repository,
        window_start=window_start,
        now=now,
        request_interval=request_interval,
        sleep=sleep,
    )
    return ScheduledCycleResult(
        mode,
        window_start,
        recent_received + history_received,
        recent_stored + history_stored,
    )


def run_scheduled(
    client: NewsClient,
    repository: Repository,
    *,
    initial_backfill_days: int = 80,
    sync_interval: float = 3_600.0,
    overlap_seconds: int = 300,
    final_refresh_interval: float = 86_400.0,
    request_interval: float = 3.0,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run recent synchronization and rolling-history coverage indefinitely."""
    while True:
        started = time.monotonic()
        cycle_time = int(clock())
        result = run_scheduled_cycle(
            client,
            repository,
            now=cycle_time,
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
        final_refresh_checkpoint = repository.get_cursor(FINAL_REFRESH_COLLECTOR_NAME)
        if (
            final_refresh_checkpoint is None
            or cycle_time - final_refresh_checkpoint >= final_refresh_interval
        ):
            refresh_started = time.monotonic()
            refresh_result = run_final_refresh(
                client,
                repository,
                interval=request_interval,
                sleep=sleep,
                now=lambda timestamp=cycle_time: datetime.fromtimestamp(timestamp, UTC),
            )
            LOGGER.info(
                "mode=scheduled phase=final_refresh refreshed=%d finalized=%d "
                "cutoff=%s duration=%.2fs",
                refresh_result.refreshed,
                refresh_result.finalized,
                refresh_result.cutoff.isoformat(),
                time.monotonic() - refresh_started,
            )
        sleep(sync_interval)
