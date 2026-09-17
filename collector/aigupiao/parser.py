"""Convert Aigupiao payloads into domain models."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from collector.models import NewsItem, StockRelation, ThemeRelation, TopicRelation


class InvalidPayload(ValueError):
    """Raised when a successful-looking payload has an invalid shape."""


def extract_title(content: str | None) -> tuple[str | None, str | None]:
    """Split a leading Chinese-bracketed title from canonical content."""
    if content is None or not content.startswith("【"):
        return None, content
    closing_bracket = content.find("】", 1)
    if closing_bracket == -1:
        return None, content
    title = content[1:closing_bracket].strip()
    if not title:
        return None, content
    body = content[closing_bracket + 1 :].lstrip()
    return title, body or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise InvalidPayload(f"expected integer, got {value!r}") from error


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return bool(value)


def _optional_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise InvalidPayload(f"expected datetime string, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise InvalidPayload(f"invalid datetime {value!r}") from error
    return parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if parsed.tzinfo is None else parsed


def _without_empty_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, item in value.items()
            if (cleaned := _without_empty_values(item)) is not None
        } or None
    if isinstance(value, list):
        return [
            cleaned
            for item in value
            if (cleaned := _without_empty_values(item)) is not None
        ] or None
    if isinstance(value, str):
        return value if value.strip() else None
    return value


def sanitize_raw_news(news: dict[str, Any]) -> dict[str, Any]:
    """Copy and minimize a news object for JSONB storage."""
    sanitized = deepcopy(news)
    sanitized.pop("part_comment", None)
    return _without_empty_values(sanitized) or {}


def _json_value(value: Any) -> Any:
    """Decode fields that are inconsistently returned as JSON strings."""
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def flatten_news(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("rslt") != "succ":
        raise InvalidPayload(f"API returned rslt={payload.get('rslt')!r}")
    grouped = payload.get("data")
    if grouped in (None, []):
        return []
    if not isinstance(grouped, (dict, list)):
        raise InvalidPayload("data must be a mapping or list")
    groups = grouped.values() if isinstance(grouped, dict) else grouped
    flattened: list[dict[str, Any]] = []
    for group in groups:
        entries = group.get("data", []) if isinstance(group, dict) else []
        if not isinstance(entries, list):
            raise InvalidPayload("date-group data must be a list")
        flattened.extend(item for item in entries if isinstance(item, dict))
    return flattened


def parse_payload(payload: dict[str, Any]) -> list[NewsItem]:
    return [parse_news(item) for item in flatten_news(payload)]


def parse_news(raw: dict[str, Any]) -> NewsItem:
    news_id = _optional_int(raw.get("id"))
    rec_time = _optional_int(raw.get("rec_time"))
    if news_id is None or rec_time is None:
        raise InvalidPayload("news id and rec_time are required")

    stocks: dict[str, StockRelation] = {}
    themes: dict[str, ThemeRelation] = {}
    topics: dict[str, TopicRelation] = {}
    for relation in raw.get("stock_infos") or []:
        if not isinstance(relation, dict):
            continue
        kind = relation.get("kind")
        if kind == "stock" and relation.get("code"):
            code = str(relation["code"])
            name = str(relation.get("name") or relation.get("content") or "")
            stocks[code] = StockRelation(code, name)
        elif kind == "theme" and relation.get("id") is not None:
            theme_id = str(relation["id"])
            themes[theme_id] = ThemeRelation(theme_id, str(relation.get("content") or ""))
    for topic in raw.get("topic") or []:
        if not isinstance(topic, dict) or topic.get("id") is None:
            continue
        topic_id = str(topic["id"])
        topics[topic_id] = TopicRelation(
            id=topic_id,
            title=str(topic.get("title") or ""),
            is_hot=_optional_bool(topic.get("is_hot")),
            old_title=topic.get("old_title"),
        )

    title, content = extract_title(raw.get("web_content"))

    return NewsItem(
        id=news_id,
        rec_time=rec_time,
        update_time=_optional_datetime(raw.get("update_time")),
        title=title,
        content=content,
        important=_optional_bool(raw.get("important")),
        important_db=_optional_bool(raw.get("important_db")),
        selection=_optional_bool(raw.get("selection")),
        app_push=_optional_bool(raw.get("app_push")),
        source=raw.get("source"),
        view_num=_optional_int(raw.get("view_num")),
        support_num=_optional_int(raw.get("support_num")),
        oppose_num=_optional_int(raw.get("oppose_num")),
        comment_num=_optional_int(raw.get("comment_num")),
        share_num=_optional_int(raw.get("share_num")),
        agq_share_num=_optional_int(raw.get("agq_share_num")),
        url=raw.get("url"),
        theme=raw.get("theme"),
        theme_quotes=_json_value(raw.get("theme_quotes")),
        concept_list=_json_value(raw.get("concept_list")),
        stock_info=_json_value(raw.get("stock_info")),
        stock_quotes=_json_value(raw.get("stock_quotes")),
        stock_code=raw.get("stock_code"),
        quote_plate=_json_value(raw.get("quote_plate")),
        is_24_hour_hot_news=_optional_bool(raw.get("is_24_hour_hot_news")),
        jump_24_hour_hot_list=_optional_bool(raw.get("jump_24_hour_hot_list")),
        express_hot_state=raw.get("set_express_hot_state"),
        raw_json=sanitize_raw_news(raw),
        stocks=tuple(stocks.values()),
        themes=tuple(themes.values()),
        topics=tuple(topics.values()),
    )
