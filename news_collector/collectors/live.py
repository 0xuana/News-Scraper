"""Latest-news polling workflow."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from news_collector.collectors.protocols import NewsClient, Repository
from news_collector.collectors.request import fetch_page

LOGGER = logging.getLogger(__name__)


def run_live(
    client: NewsClient,
    repository: Repository,
    *,
    interval: float = 45.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        started = time.monotonic()
        page = fetch_page(client, before=0, collector_name="aigupiao_live")
        items = page.items
        repository.save_batch(items, request_coverage=page.coverage)
        LOGGER.info(
            "mode=live before=0 received=%d duration=%.2fs",
            len(items),
            time.monotonic() - started,
        )
        sleep(interval)
