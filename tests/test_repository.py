from typing import Any

import pytest

from news_collector.aigupiao.parser import parse_payload
from news_collector.db.repository import NEWS_UPSERT, NewsRepository, coverage_gaps


class Transaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.rolled_back = exc_type is not None


class FailingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.tx = Transaction()

    def __enter__(self) -> "FailingConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        return None

    def transaction(self) -> Transaction:
        return self.tx

    def execute(self, statement: str, params: Any = None) -> None:
        self.statements.append(statement)
        raise RuntimeError("database write failed")


def test_failed_news_write_rolls_back_before_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    item = parse_payload({
        "rslt": "succ",
        "data": {"day": {"data": [{"id": "1", "rec_time": "100"}]}},
    })[0]
    connection = FailingConnection()
    monkeypatch.setattr(
        "news_collector.db.repository.psycopg.connect", lambda database_url: connection
    )

    with pytest.raises(RuntimeError, match="database write failed"):
        NewsRepository("postgresql://test").save_batch(
            [item], collector_name="aigupiao_backfill", cursor=100
        )

    assert connection.tx.rolled_back
    assert not any("crawler_state" in statement for statement in connection.statements)


def test_news_params_include_extracted_title() -> None:
    item = parse_payload({
        "rslt": "succ",
        "data": {"day": {"data": [{
            "id": "1",
            "rec_time": "100",
            "web_content": "【Title】Body",
        }]}},
    })[0]

    params = NewsRepository._news_params(item)

    assert params["title"] == "Title"
    assert params["content"] == "Body"


def test_existing_news_updates_only_engagement_counters() -> None:
    update_clause = NEWS_UPSERT.split("ON CONFLICT (id) DO UPDATE SET", 1)[1]

    for column in (
        "view_num",
        "support_num",
        "oppose_num",
        "comment_num",
        "share_num",
        "agq_share_num",
    ):
        assert f"{column} = EXCLUDED.{column}" in update_clause
    for column in ("title", "content", "raw_json", "stock_info", "theme"):
        assert f"{column} = EXCLUDED.{column}" not in update_clause
    assert "WHERE news.finalized_at IS NULL" in update_clause


def test_coverage_gaps_merges_overlapping_and_adjacent_intervals() -> None:
    intervals = [(40, 60), (10, 30), (25, 40), (80, 120)]

    assert coverage_gaps(intervals, 0, 100) == [(0, 10), (60, 80)]


def test_coverage_gaps_reports_whole_window_without_requests() -> None:
    assert coverage_gaps([], 100, 200) == [(100, 200)]
