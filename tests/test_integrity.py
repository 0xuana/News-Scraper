from typing import Any

import pytest

from news_collector.collectors.integrity import (
    CHECKPOINT_NAME,
    CoverageIncomplete,
    run_coverage_check,
)
from news_collector.db.repository import coverage_gaps


def payload(*times: int) -> dict[str, Any]:
    return {
        "rslt": "succ",
        "data": {"day": {"data": [
            {"id": str(value), "rec_time": str(value), "stock_infos": []}
            for value in times
        ]}},
    }


class FakeClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = iter(responses)
        self.before: list[int] = []

    def fetch(self, before: int = 0) -> dict[str, Any]:
        self.before.append(before)
        return next(self.responses)


class FakeRepository:
    def __init__(self, intervals: list[tuple[int, int]]) -> None:
        self.intervals = intervals
        self.checkpoints: dict[str, int] = {}

    def find_coverage_gaps(self, start: int, end: int) -> list[tuple[int, int]]:
        return coverage_gaps(self.intervals, start, end)

    def save_batch(self, items: Any, **kwargs: Any) -> None:
        request = kwargs.get("request_coverage")
        if request is not None:
            self.intervals.append((request.coverage_start, request.coverage_end))
        if kwargs.get("collector_name") is not None:
            self.checkpoints[kwargs["collector_name"]] = kwargs["cursor"]


def test_coverage_check_fetches_backward_until_gap_is_closed() -> None:
    repository = FakeRepository([(13_600, 20_000), (50_000, 100_000)])
    client = FakeClient([payload(45_000, 30_000), payload(25_000, 19_000)])

    result = run_coverage_check(
        client,
        repository,
        now=100_000,
        initial_backfill_days=1,
        request_interval=0,
        sleep=lambda _: None,
    )

    assert client.before == [50_000, 30_000]
    assert repository.checkpoints[CHECKPOINT_NAME] == 100_000
    assert result.gaps_found == 1
    assert result.requests_made == 2


def test_coverage_check_does_not_claim_empty_interval() -> None:
    repository = FakeRepository([(13_600, 20_000), (50_000, 100_000)])

    with pytest.raises(CoverageIncomplete, match="1 request-coverage gap"):
        run_coverage_check(
            FakeClient([payload()]),
            repository,
            now=100_000,
            initial_backfill_days=1,
            request_interval=0,
            sleep=lambda _: None,
        )

    assert CHECKPOINT_NAME not in repository.checkpoints
