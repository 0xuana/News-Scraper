"""Transactional PostgreSQL repository."""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib.resources import files

import psycopg

from news_collector.models import NewsItem

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
    rec_time = EXCLUDED.rec_time,
    published_at = EXCLUDED.published_at,
    update_time = EXCLUDED.update_time,
    title = EXCLUDED.title,
    content = EXCLUDED.content,
    important = EXCLUDED.important,
    important_db = EXCLUDED.important_db,
    selection = EXCLUDED.selection,
    app_push = EXCLUDED.app_push,
    source = EXCLUDED.source,
    view_num = EXCLUDED.view_num,
    support_num = EXCLUDED.support_num,
    oppose_num = EXCLUDED.oppose_num,
    comment_num = EXCLUDED.comment_num,
    share_num = EXCLUDED.share_num,
    agq_share_num = EXCLUDED.agq_share_num,
    url = EXCLUDED.url,
    theme = EXCLUDED.theme,
    theme_quotes = EXCLUDED.theme_quotes,
    concept_list = EXCLUDED.concept_list,
    stock_info = EXCLUDED.stock_info,
    stock_quotes = EXCLUDED.stock_quotes,
    stock_code = EXCLUDED.stock_code,
    quote_plate = EXCLUDED.quote_plate,
    is_24_hour_hot_news = EXCLUDED.is_24_hour_hot_news,
    jump_24_hour_hot_list = EXCLUDED.jump_24_hour_hot_list,
    express_hot_state = EXCLUDED.express_hot_state,
    raw_json = EXCLUDED.raw_json,
    last_collected_at = now()
WHERE news.finalized_at IS NULL
RETURNING id
"""


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
    ) -> None:
        if (collector_name is None) != (cursor is None):
            raise ValueError("collector_name and cursor must be supplied together")
        with psycopg.connect(self._database_url) as connection, connection.transaction():
            for item in items:
                saved = connection.execute(NEWS_UPSERT, self._news_params(item)).fetchone()
                if saved is None:
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
            if collector_name is not None:
                connection.execute(
                    """INSERT INTO crawler_state (collector_name, cursor)
                       VALUES (%s, %s)
                       ON CONFLICT (collector_name) DO UPDATE
                       SET cursor = EXCLUDED.cursor, updated_at = now()""",
                    (collector_name, cursor),
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
