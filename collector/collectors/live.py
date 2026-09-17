"""Latest-news polling workflow."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from collector.aigupiao.parser import parse_payload
from collector.collectors.protocols import NewsClient, Repository

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
        items = parse_payload(client.fetch(0))
        repository.save_batch(items)
        LOGGER.info(
            "mode=live before=0 received=%d duration=%.2fs",
            len(items),
            time.monotonic() - started,
        )
        sleep(interval)

