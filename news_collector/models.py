"""Domain models shared by parsers and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StockRelation:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class ThemeRelation:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class TopicRelation:
    id: str
    title: str
    is_hot: bool | None
    old_title: str | None


@dataclass(frozen=True, slots=True)
class NewsItem:
    id: int
    rec_time: int
    update_time: datetime | None
    title: str | None
    content: str | None
    important: bool | None
    important_db: bool | None
    selection: bool | None
    app_push: bool | None
    source: str | None
    view_num: int | None
    support_num: int | None
    oppose_num: int | None
    comment_num: int | None
    share_num: int | None
    agq_share_num: int | None
    url: str | None
    theme: str | None
    theme_quotes: Any
    concept_list: Any
    stock_info: Any
    stock_quotes: Any
    stock_code: str | None
    quote_plate: Any
    is_24_hour_hot_news: bool | None
    jump_24_hour_hot_list: bool | None
    express_hot_state: str | None
    raw_json: dict[str, Any]
    stocks: tuple[StockRelation, ...] = field(default_factory=tuple)
    themes: tuple[ThemeRelation, ...] = field(default_factory=tuple)
    topics: tuple[TopicRelation, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RequestCoverage:
    """Auditable time range returned by one successful API request."""

    request_id: UUID
    collector_name: str
    requested_before: int
    coverage_start: int
    coverage_end: int
    news_ids: tuple[int, ...]
    requested_at: int
