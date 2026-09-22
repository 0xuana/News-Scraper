"""Command-line entry point for the collector."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from news_collector.aigupiao.client import AigupiaoClient
from news_collector.aigupiao.parser import parse_payload
from news_collector.collectors.backfill import run_backfill
from news_collector.collectors.final_refresh import run_final_refresh
from news_collector.collectors.live import run_live
from news_collector.collectors.scheduled import run_scheduled
from news_collector.config import Settings
from news_collector.db.repository import NewsRepository
from news_collector.utils.logging import configure_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="news-collector",
        description="Collect Aigupiao news into PostgreSQL.",
        epilog=(
            "Collection timing, retry behavior, and scheduled windows are configured with "
            "environment variables documented in README.md."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    backfill = subparsers.add_parser(
        "backfill",
        help="resume unbounded historical pagination",
        description=(
            "Page backward until the API returns no news, saving a page checkpoint after "
            "each successful database transaction."
        ),
    )
    backfill.add_argument(
        "--before",
        type=int,
        metavar="UNIX_TIMESTAMP",
        help=(
            "start before this Unix timestamp instead of the saved backfill cursor; "
            "0 starts at the newest page"
        ),
    )
    subparsers.add_parser(
        "live",
        help="poll only the newest page continuously",
        description=(
            "Fetch before=0 repeatedly at LIVE_INTERVAL; this does not paginate and relies "
            "on news-ID UPSERTs for deduplication."
        ),
    )
    scheduled = subparsers.add_parser(
        "scheduled",
        help="run bounded syncs and automatic final refreshes",
        description=(
            "Backfill INITIAL_BACKFILL_DAYS once, then synchronize from the last successful "
            "cycle checkpoint with overlap every SYNC_INTERVAL. Also runs final-refresh when "
            "FINAL_REFRESH_INTERVAL has elapsed."
        ),
    )
    scheduled.add_argument(
        "--verify-coverage",
        action="store_true",
        help=(
            "audit the latest INITIAL_BACKFILL_DAYS daily and fetch any missing "
            "request intervals"
        ),
    )
    subparsers.add_parser(
        "final-refresh",
        help="refresh one-month-old news and freeze it",
        description=(
            "Page from newest news through the one-calendar-month boundary, update mutable "
            "fields, then mark all due rows immutable. Scheduled mode runs this automatically."
        ),
    )
    probe = subparsers.add_parser(
        "probe",
        help="inspect one API page without database writes",
        description=(
            "Convert the start of an Asia/Shanghai calendar date to a Unix cursor, fetch one "
            "page, and print its cursor and parsed item count as JSON."
        ),
    )
    probe.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Asia/Shanghai date whose 00:00 timestamp is sent as the API before cursor",
    )
    subparsers.add_parser(
        "init-db",
        help="create or update PostgreSQL tables",
        description="Apply the idempotent bundled PostgreSQL schema and exit.",
    )
    return parser


def _date_cursor(value: str) -> int:
    parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(parsed.timestamp())


def main() -> int:
    args = _parser().parse_args()
    configure_logging()
    settings = Settings.from_env(require_database=args.command != "probe")

    if args.command == "init-db":
        NewsRepository(settings.database_url).initialize()
        return 0

    with AigupiaoClient(
        settings.base_url,
        timeout=settings.http_timeout,
        max_retries=settings.max_retries,
        max_backoff=settings.max_backoff,
    ) as client:
        if args.command == "backfill":
            repository = NewsRepository(settings.database_url)
            run_backfill(
                client,
                repository,
                before=args.before,
                interval=settings.request_interval,
            )
        elif args.command == "live":
            repository = NewsRepository(settings.database_url)
            run_live(client, repository, interval=settings.live_interval)
        elif args.command == "scheduled":
            repository = NewsRepository(settings.database_url)
            run_scheduled(
                client,
                repository,
                initial_backfill_days=settings.initial_backfill_days,
                sync_interval=settings.sync_interval,
                overlap_seconds=settings.sync_overlap_seconds,
                final_refresh_interval=settings.final_refresh_interval,
                verify_coverage=args.verify_coverage,
                coverage_check_interval=settings.coverage_check_interval,
                coverage_retry_interval=settings.coverage_retry_interval,
                request_interval=settings.request_interval,
            )
        elif args.command == "final-refresh":
            repository = NewsRepository(settings.database_url)
            run_final_refresh(client, repository, interval=settings.request_interval)
        else:
            cursor = _date_cursor(args.date)
            items = parse_payload(client.fetch(cursor))
            print(json.dumps({"before": cursor, "received": len(items)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
