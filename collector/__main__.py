"""Command-line entry point for the collector."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from collector.aigupiao.client import AigupiaoClient
from collector.aigupiao.parser import parse_payload
from collector.collectors.backfill import run_backfill
from collector.collectors.final_refresh import run_final_refresh
from collector.collectors.live import run_live
from collector.config import Settings
from collector.db.repository import NewsRepository
from collector.utils.logging import configure_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Aigupiao news into PostgreSQL")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backfill = subparsers.add_parser("backfill", help="resume historical collection")
    backfill.add_argument("--before", type=int, help="override the stored starting cursor")
    subparsers.add_parser("live", help="poll current news continuously")
    subparsers.add_parser(
        "final-refresh", help="refresh one-month-old news and freeze it for long-term storage"
    )
    probe = subparsers.add_parser("probe", help="fetch one page near a date")
    probe.add_argument("--date", required=True, help="date in YYYY-MM-DD format")
    subparsers.add_parser("init-db", help="create the PostgreSQL tables")
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
