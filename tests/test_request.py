from typing import Any

from news_collector.collectors.request import fetch_page


class FakeClient:
    def fetch(self, before: int = 0) -> dict[str, Any]:
        return {
            "rslt": "succ",
            "data": {"day": {"data": [
                {"id": "7", "rec_time": "900", "stock_infos": []},
                {"id": "8", "rec_time": "800", "stock_infos": []},
            ]}},
        }


def test_latest_request_coverage_uses_request_time_and_oldest_news() -> None:
    page = fetch_page(
        FakeClient(), before=0, collector_name="test", clock=lambda: 1_000
    )

    assert page.coverage.requested_before == 0
    assert page.coverage.coverage_start == 800
    assert page.coverage.coverage_end == 1_000
    assert page.coverage.news_ids == (7, 8)
    assert page.coverage.request_id.version == 4
