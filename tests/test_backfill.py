from typing import Any

import pytest

from news_collector.collectors.backfill import COLLECTOR_NAME, CursorNotAdvancing, run_backfill


def payload(*times: int) -> dict[str, Any]:
    return {
        "rslt": "succ",
        "data": {"day": {"data": [
            {"id": str(index), "rec_time": str(value), "stock_infos": []}
            for index, value in enumerate(times, start=1)
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
    def __init__(self, cursor: int | None = None) -> None:
        self.cursor = cursor
        self.saved: list[tuple[list[int], str | None, int | None]] = []

    def get_cursor(self, collector_name: str) -> int | None:
        assert collector_name == COLLECTOR_NAME
        return self.cursor

    def save_batch(self, items: Any, *, collector_name: str | None = None,
                   cursor: int | None = None, **kwargs: Any) -> None:
        self.saved.append(([item.id for item in items], collector_name, cursor))


def test_backfill_calculates_cursor_and_stops_on_empty_page() -> None:
    client = FakeClient([payload(100, 90, 90), payload()])
    repository = FakeRepository()

    result = run_backfill(client, repository, interval=0, sleep=lambda _: None)

    assert client.before == [0, 90]
    assert repository.saved == [([1, 2, 3], COLLECTOR_NAME, 90), ([], None, None)]
    assert result.total_processed == 3
    assert result.oldest_time == 90


def test_backfill_restarts_from_checkpoint() -> None:
    client = FakeClient([payload()])

    run_backfill(client, FakeRepository(cursor=123), interval=0, sleep=lambda _: None)

    assert client.before == [123]


def test_backfill_rejects_non_advancing_cursor() -> None:
    client = FakeClient([payload(100, 101)])

    with pytest.raises(CursorNotAdvancing):
        run_backfill(client, FakeRepository(cursor=100), interval=0, sleep=lambda _: None)
