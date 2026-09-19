from typing import Any

import pytest

from news_collector.collectors.final_refresh import COLLECTOR_NAME as FINAL_REFRESH_NAME
from news_collector.collectors.scheduled import (
    COLLECTOR_NAME,
    HISTORY_COVERAGE_NAME,
    HISTORY_EMPTY_COUNT_NAME,
    HISTORY_PROGRESS_NAME,
    run_scheduled,
    run_scheduled_cycle,
)


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
    def __init__(self, **state: int) -> None:
        self.state = state
        self.saved: list[tuple[list[int], dict[str, int]]] = []
        self.finalize_calls = 0

    def get_cursor(self, collector_name: str) -> int | None:
        return self.state.get(collector_name)

    def save_batch(
        self,
        items: Any,
        *,
        collector_name: str | None = None,
        cursor: int | None = None,
        checkpoints: dict[str, int] | None = None,
    ) -> None:
        state = dict(checkpoints or {})
        if collector_name is not None and cursor is not None:
            state[collector_name] = cursor
        self.saved.append(([item.rec_time for item in items], state))
        self.state.update(state)

    def finalize_due(self) -> int:
        self.finalize_calls += 1
        return 2


def test_first_cycle_fetches_current_news_then_covers_history() -> None:
    client = FakeClient(
        [payload(100_000, 80_000), payload(100_000, 80_000), payload(70_000, 13_000)]
    )
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

    assert client.before == [0, 0, 80_000]
    assert repository.state[COLLECTOR_NAME] == 100_000
    assert repository.state[HISTORY_PROGRESS_NAME] == 13_000
    assert repository.state[HISTORY_COVERAGE_NAME] == 13_600
    assert result.mode == "initial"
    assert result.window_start == 13_600


def test_restart_catches_up_recent_news_before_resuming_history() -> None:
    client = FakeClient(
        [payload(103_500, 102_000), payload(100_500, 99_600), payload(79_000, 13_000)]
    )
    repository = FakeRepository(
        **{COLLECTOR_NAME: 100_000, HISTORY_PROGRESS_NAME: 80_000}
    )

    run_scheduled_cycle(
        client,
        repository,
        now=103_600,
        initial_backfill_days=1,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0, 102_000, 80_000]
    assert repository.state[HISTORY_COVERAGE_NAME] == 17_200


def test_completed_coverage_skips_historical_requests() -> None:
    client = FakeClient([payload(103_500, 99_600)])
    repository = FakeRepository(
        **{COLLECTOR_NAME: 100_000, HISTORY_COVERAGE_NAME: 10_000}
    )

    run_scheduled_cycle(
        client,
        repository,
        now=103_600,
        initial_backfill_days=1,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0]


def test_larger_history_window_extends_previous_coverage() -> None:
    client = FakeClient([payload(200_000, 189_000), payload(99_000, 20_000)])
    repository = FakeRepository(
        **{
            COLLECTOR_NAME: 190_000,
            HISTORY_PROGRESS_NAME: 100_000,
            HISTORY_COVERAGE_NAME: 100_000,
        }
    )

    run_scheduled_cycle(
        client,
        repository,
        now=200_000,
        initial_backfill_days=2,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0, 100_000]
    assert repository.state[HISTORY_COVERAGE_NAME] == 27_200


def test_ten_empty_probes_advance_by_ten_minutes_and_mark_coverage() -> None:
    client = FakeClient([payload(), *[payload() for _ in range(10)]])
    repository = FakeRepository(**{HISTORY_PROGRESS_NAME: 50_000})

    run_scheduled_cycle(
        client,
        repository,
        now=100_000,
        initial_backfill_days=1,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0, 50_000, 49_400, 48_800, 48_200, 47_600, 47_000,
                             46_400, 45_800, 45_200, 44_600]
    assert repository.state[HISTORY_EMPTY_COUNT_NAME] == 0
    assert repository.state[HISTORY_COVERAGE_NAME] == 13_600


def test_empty_probe_count_resumes_after_restart() -> None:
    client = FakeClient([payload(100_000), payload(), payload()])
    repository = FakeRepository(
        **{HISTORY_PROGRESS_NAME: 44_600, HISTORY_EMPTY_COUNT_NAME: 9}
    )

    run_scheduled_cycle(
        client,
        repository,
        now=100_000,
        initial_backfill_days=1,
        overlap_seconds=300,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [0, 44_600]
    assert repository.state[HISTORY_COVERAGE_NAME] == 13_600


def test_recent_checkpoint_does_not_advance_when_pagination_fails() -> None:
    client = FakeClient([payload(103_500, 102_000)])
    repository = FakeRepository(**{COLLECTOR_NAME: 100_000})

    with pytest.raises(StopIteration):
        run_scheduled_cycle(
            client,
            repository,
            now=103_600,
            initial_backfill_days=1,
            overlap_seconds=300,
            request_interval=0,
            sleep=lambda _: None,
        )

    assert repository.state[COLLECTOR_NAME] == 100_000


def test_scheduler_runs_final_refresh_after_complete_cycle() -> None:
    client = FakeClient([payload(100_000, 13_000), payload()])
    repository = FakeRepository(**{HISTORY_COVERAGE_NAME: 0})
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
    assert repository.state[FINAL_REFRESH_NAME] == 100_000


def test_scheduler_skips_final_refresh_until_interval_elapses() -> None:
    client = FakeClient([payload(100_000, 13_000)])
    repository = FakeRepository(
        **{HISTORY_COVERAGE_NAME: 0, FINAL_REFRESH_NAME: 99_500}
    )
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
