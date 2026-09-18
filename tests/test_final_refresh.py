from datetime import UTC, datetime
from typing import Any

from collector.collectors.final_refresh import COLLECTOR_NAME, one_month_ago, run_final_refresh


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
    def __init__(self) -> None:
        self.saved = 0
        self.finalize_calls = 0
        self.checkpoint: int | None = None

    def get_cursor(self, collector_name: str) -> int | None:
        return None

    def save_batch(self, items: Any, **kwargs: Any) -> None:
        self.saved += len(items)
        if kwargs.get("collector_name") == COLLECTOR_NAME:
            self.checkpoint = kwargs["cursor"]

    def finalize_due(self) -> int:
        self.finalize_calls += 1
        return 4


def test_one_month_ago_clamps_end_of_month() -> None:
    assert one_month_ago(datetime(2026, 3, 31, tzinfo=UTC)) == datetime(
        2026, 2, 28, tzinfo=UTC
    )


def test_final_refresh_scans_to_cutoff_before_freezing() -> None:
    now = datetime(2026, 9, 17, tzinfo=UTC)
    cutoff = int(datetime(2026, 8, 17, tzinfo=UTC).timestamp())
    client = FakeClient([payload(cutoff + 100, cutoff + 10), payload(cutoff, cutoff - 1)])
    repository = FakeRepository()

    result = run_final_refresh(
        client,
        repository,
        interval=0,
        sleep=lambda _: None,
        now=lambda: now,
    )

    assert client.before == [0, cutoff + 10]
    assert repository.saved == 4
    assert repository.finalize_calls == 1
    assert repository.checkpoint == int(now.timestamp())
    assert result.finalized == 4
