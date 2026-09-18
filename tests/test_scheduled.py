from typing import Any

import pytest

from collector.collectors.final_refresh import COLLECTOR_NAME as FINAL_REFRESH_COLLECTOR_NAME
from collector.collectors.scheduled import COLLECTOR_NAME, run_scheduled, run_scheduled_cycle


def payload(*times: int) -> dict[str, Any]:
    return {
        "rslt": "succ",
        "data": {
            "day": {
                "data": [
                    {"id": str(index), "rec_time": str(value), "stock_infos": []}
                    for index, value in enumerate(times, start=1)
                ]
            }
        },
    }


class FakeClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.before: list[int] = []

    def fetch(self, before: int = 0) -> dict[str, Any]:
        self.before.append(before)
        return next(self.responses)


class FakeRepository:
    def __init__(
        self,
        cursor: int | None = None,
        final_refresh_cursor: int | None = None,
    ) -> None:
        self.cursor = cursor
        self.final_refresh_cursor = final_refresh_cursor
        self.saved: list[tuple[list[int], str | None, int | None]] = []
        self.finalize_calls = 0

    def get_cursor(self, collector_name: str) -> int | None:
        if collector_name == COLLECTOR_NAME:
            return self.cursor
        assert collector_name == FINAL_REFRESH_COLLECTOR_NAME
        return self.final_refresh_cursor

    def save_batch(
        self,
        items: Any,
        *,
        collector_name: str | None = None,
        cursor: int | None = None,
    ) -> None:
        self.saved.append(([item.rec_time for item in items], collector_name, cursor))
        if collector_name == COLLECTOR_NAME:
            self.cursor = cursor
        elif collector_name == FINAL_REFRESH_COLLECTOR_NAME:
            self.final_refresh_cursor = cursor

    def finalize_due(self) -> int:
        self.finalize_calls += 1
        return 2


def test_initial_cycle_stops_at_configured_history_cutoff() -> None:
    client = FakeClient([payload(100_000, 80_000), payload(70_000, 13_000, 12_000)])
    repository = FakeRepository()

    result = run_scheduled_cycle(
        client,
        repository,
        now=100_000,
        initial_backfill_days=1,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0, 80_000]
    assert repository.saved == [
        ([100_000, 80_000], None, None),
        ([70_000], None, None),
        ([], COLLECTOR_NAME, 100_000),
    ]
    assert result.mode == "initial"
    assert result.window_start == 13_600
    assert result.stored == 3


def test_incremental_cycle_pages_until_checkpoint_overlap() -> None:
    client = FakeClient([payload(103_500, 102_000), payload(100_500, 99_600)])
    repository = FakeRepository(cursor=100_000)

    result = run_scheduled_cycle(
        client,
        repository,
        now=103_600,
        initial_backfill_days=60,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0, 102_000]
    assert repository.saved == [
        ([103_500, 102_000], None, None),
        ([100_500], None, None),
        ([], COLLECTOR_NAME, 103_600),
    ]
    assert result.mode == "incremental"
    assert result.window_start == 99_700
    assert result.stored == 3


def test_cycle_does_not_advance_checkpoint_when_pagination_fails() -> None:
    client = FakeClient([payload(103_500, 102_000)])
    repository = FakeRepository(cursor=100_000)

    with pytest.raises(StopIteration):
        run_scheduled_cycle(
            client,
            repository,
            now=103_600,
            initial_backfill_days=60,
            overlap_seconds=300,
            request_interval=0,
            sleep=lambda _: None,
        )

    assert repository.cursor == 100_000


def test_scheduler_sleeps_for_configured_interval_after_complete_cycle() -> None:
    client = FakeClient([payload(100_000, 13_000), payload()])
    repository = FakeRepository()
    sleeps: list[float] = []

    def stop_after_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise RuntimeError("stop scheduler")

    with pytest.raises(RuntimeError, match="stop scheduler"):
        run_scheduled(
            client,
            repository,
            initial_backfill_days=1,
            sync_interval=3_600,
            overlap_seconds=300,
            request_interval=0,
            clock=lambda: 100_000,
            sleep=stop_after_sleep,
        )

    assert sleeps == [3_600]
    assert repository.finalize_calls == 1
    assert repository.final_refresh_cursor == 100_000


def test_scheduler_skips_final_refresh_until_its_interval_elapses() -> None:
    client = FakeClient([payload(100_000, 13_000)])
    repository = FakeRepository(final_refresh_cursor=99_500)
    sleeps: list[float] = []

    def stop_after_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise RuntimeError("stop scheduler")

    with pytest.raises(RuntimeError, match="stop scheduler"):
        run_scheduled(
            client,
            repository,
            initial_backfill_days=1,
            sync_interval=3_600,
            overlap_seconds=300,
            final_refresh_interval=1_000,
            request_interval=0,
            clock=lambda: 100_000,
            sleep=stop_after_sleep,
        )

    assert sleeps == [3_600]
    assert repository.finalize_calls == 0
