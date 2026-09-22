"""Transactional PostgreSQL repository."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from importlib.resources import files

import psycopg

from news_collector.models import NewsItem, RequestCoverage

NEWS_UPSERT = """
INSERT INTO news (
    id, rec_time, published_at, update_time, title, content,
    important, important_db, selection, app_push, source, view_num, support_num,
    oppose_num, comment_num, share_num, agq_share_num, url, theme, theme_quotes,
    concept_list, stock_info, stock_quotes, stock_code, quote_plate,
    is_24_hour_hot_news, jump_24_hour_hot_list, express_hot_state, raw_json,
    mutable_until
) VALUES (
    %(id)s, %(rec_time)s, to_timestamp(%(rec_time)s), %(update_time)s, %(title)s,
    %(content)s,
    %(important)s, %(important_db)s, %(selection)s,
    %(app_push)s, %(source)s, %(view_num)s, %(support_num)s, %(oppose_num)s,
    %(comment_num)s, %(share_num)s, %(agq_share_num)s, %(url)s, %(theme)s,
    %(theme_quotes)s::jsonb, %(concept_list)s::jsonb, %(stock_info)s::jsonb,
    %(stock_quotes)s::jsonb, %(stock_code)s, %(quote_plate)s::jsonb,
    %(is_24_hour_hot_news)s, %(jump_24_hour_hot_list)s, %(express_hot_state)s,
    %(raw_json)s::jsonb, to_timestamp(%(rec_time)s) + interval '1 month'
)
ON CONFLICT (id) DO UPDATE SET
    view_num = EXCLUDED.view_num,
    support_num = EXCLUDED.support_num,
    oppose_num = EXCLUDED.oppose_num,
    comment_num = EXCLUDED.comment_num,
    share_num = EXCLUDED.share_num,
    agq_share_num = EXCLUDED.agq_share_num,
    last_collected_at = now()
WHERE news.finalized_at IS NULL
RETURNING id, (xmax = 0) AS inserted
"""


def coverage_gaps(
    intervals: Sequence[tuple[int, int]], window_start: int, window_end: int
) -> list[tuple[int, int]]:
    """Return the complement of ordered or unordered coverage intervals."""
    if window_start >= window_end:
        raise ValueError("window_start must be earlier than window_end")
    gaps: list[tuple[int, int]] = []
    covered_until = window_start
    for raw_start, raw_end in sorted(intervals):
        start = max(window_start, raw_start)
        end = min(window_end, raw_end)
        if end <= covered_until:
            continue
        if start > covered_until:
            gaps.append((covered_until, start))
        covered_until = max(covered_until, end)
        if covered_until >= window_end:
            break
    if covered_until < window_end:
        gaps.append((covered_until, window_end))
    return gaps


class NewsRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def initialize(self) -> None:
        schema = files("news_collector.db").joinpath("schema.sql").read_text()
        with psycopg.connect(self._database_url) as connection:
            connection.execute(schema)

    def get_cursor(self, collector_name: str) -> int | None:
        with psycopg.connect(self._database_url) as connection:
            row = connection.execute(
                "SELECT cursor FROM crawler_state WHERE collector_name = %s",
                (collector_name,),
            ).fetchone()
        return int(row[0]) if row else None

    def save_batch(
        self,
        items: Sequence[NewsItem],
        *,
        collector_name: str | None = None,
        cursor: int | None = None,
        checkpoints: Mapping[str, int] | None = None,
        request_coverage: RequestCoverage | None = None,
    ) -> None:
        if (collector_name is None) != (cursor is None):
            raise ValueError("collector_name and cursor must be supplied together")
        if checkpoints is not None and collector_name is not None:
            raise ValueError("use either checkpoints or collector_name/cursor")
        state = dict(checkpoints or {})
        if collector_name is not None and cursor is not None:
            state[collector_name] = cursor
        with psycopg.connect(self._database_url) as connection, connection.transaction():
            for item in items:
                saved = connection.execute(NEWS_UPSERT, self._news_params(item)).fetchone()
                if saved is None:
                    continue
                if not saved[1]:
                    continue
                for stock in item.stocks:
                    connection.execute(
                        """INSERT INTO news_stock (news_id, stock_code, stock_name)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (news_id, stock_code) DO UPDATE
                           SET stock_name = EXCLUDED.stock_name""",
                        (item.id, stock.code, stock.name),
                    )
                for theme in item.themes:
                    connection.execute(
                        """INSERT INTO news_theme (news_id, theme_id, theme_name)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (news_id, theme_id) DO UPDATE
                           SET theme_name = EXCLUDED.theme_name""",
                        (item.id, theme.id, theme.name),
                    )
                for topic in item.topics:
                    connection.execute(
                        """INSERT INTO news_topic (
                               news_id, topic_id, topic_title, is_hot, old_title
                           ) VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (news_id, topic_id) DO UPDATE SET
                               topic_title = EXCLUDED.topic_title,
                               is_hot = EXCLUDED.is_hot,
                               old_title = EXCLUDED.old_title""",
                        (item.id, topic.id, topic.title, topic.is_hot, topic.old_title),
                    )
            for state_name, state_cursor in state.items():
                connection.execute(
                    """INSERT INTO crawler_state (collector_name, cursor)
                       VALUES (%s, %s)
                       ON CONFLICT (collector_name) DO UPDATE
                       SET cursor = EXCLUDED.cursor, updated_at = now()""",
                    (state_name, state_cursor),
                )
            if request_coverage is not None:
                connection.execute(
                    """INSERT INTO request_coverage (
                           request_id, collector_name, requested_before,
                           coverage_start, coverage_end, news_ids, news_count, requested_at
                       ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, to_timestamp(%s))""",
                    (
                        request_coverage.request_id,
                        request_coverage.collector_name,
                        request_coverage.requested_before,
                        request_coverage.coverage_start,
                        request_coverage.coverage_end,
                        json.dumps(request_coverage.news_ids),
                        len(request_coverage.news_ids),
                        request_coverage.requested_at,
                    ),
                )

    def find_coverage_gaps(
        self, window_start: int, window_end: int
    ) -> list[tuple[int, int]]:
        """Return uncovered ranges after merging all successful request intervals."""
        if window_start >= window_end:
            raise ValueError("window_start must be earlier than window_end")
        with psycopg.connect(self._database_url) as connection:
            rows = connection.execute(
                """SELECT coverage_start, coverage_end
                   FROM request_coverage
                   WHERE coverage_end > %s AND coverage_start < %s
                   ORDER BY coverage_start, coverage_end""",
                (window_start, window_end),
            ).fetchall()

        return coverage_gaps(
            [(int(start), int(end)) for start, end in rows], window_start, window_end
        )

    def finalize_due(self) -> int:
        """Freeze entries whose one-month mutable period has elapsed."""
        with psycopg.connect(self._database_url) as connection:
            result = connection.execute(
                """UPDATE news
                   SET finalized_at = now()
                   WHERE finalized_at IS NULL AND mutable_until <= now()"""
            )
            return result.rowcount

    @staticmethod
    def _news_params(item: NewsItem) -> dict[str, object]:
        return {
            "id": item.id,
            "rec_time": item.rec_time,
            "update_time": item.update_time,
            "title": item.title,
            "content": item.content,
            "important": item.important,
            "important_db": item.important_db,
            "selection": item.selection,
            "app_push": item.app_push,
            "source": item.source,
            "view_num": item.view_num,
            "support_num": item.support_num,
            "oppose_num": item.oppose_num,
            "comment_num": item.comment_num,
            "share_num": item.share_num,
            "agq_share_num": item.agq_share_num,
            "url": item.url,
            "theme": item.theme,
            "theme_quotes": json.dumps(item.theme_quotes, ensure_ascii=False),
            "concept_list": json.dumps(item.concept_list, ensure_ascii=False),
            "stock_info": json.dumps(item.stock_info, ensure_ascii=False),
            "stock_quotes": json.dumps(item.stock_quotes, ensure_ascii=False),
            "stock_code": item.stock_code,
            "quote_plate": json.dumps(item.quote_plate, ensure_ascii=False),
            "is_24_hour_hot_news": item.is_24_hour_hot_news,
            "jump_24_hour_hot_list": item.jump_24_hour_hot_list,
            "express_hot_state": item.express_hot_state,
            "raw_json": json.dumps(item.raw_json, ensure_ascii=False),
        }
