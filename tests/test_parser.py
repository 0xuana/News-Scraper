import json
from pathlib import Path

import pytest

from collector.aigupiao.parser import (
    InvalidPayload,
    extract_title,
    parse_payload,
)

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("fixture", ["news.json", "news2.json"])
def test_real_response_fixture_parses_twenty_news(fixture: str) -> None:
    payload = json.loads((ROOT / fixture).read_text())

    items = parse_payload(payload)

    assert len(items) == 20
    assert all(isinstance(item.id, int) and isinstance(item.rec_time, int) for item in items)
    assert all(item.update_time is not None and item.update_time.tzinfo for item in items)
    assert all("part_comment" not in item.raw_json for item in items)


def test_extended_metadata_is_parsed_from_real_response() -> None:
    payload = json.loads((ROOT / "news.json").read_text())

    items = parse_payload(payload)
    item = next(news for news in items if news.theme and news.topics)

    assert isinstance(item.theme_quotes, dict)
    assert isinstance(item.concept_list, list)
    assert isinstance(item.stock_info, list)
    assert isinstance(item.stock_quotes, dict)
    assert item.share_num is not None
    assert item.agq_share_num is not None
    assert item.topics[0].title.startswith("#")


def test_hot_news_flags_are_not_treated_as_comment_pinning() -> None:
    payload = json.loads((ROOT / "news.json").read_text())

    hot = next(item for item in parse_payload(payload) if item.is_24_hour_hot_news)

    assert hot.jump_24_hour_hot_list is True
    assert hot.express_hot_state == "down_24_hour_hot_news"
    assert not hasattr(hot, "is_pinned")


def test_real_web_content_is_stored_without_html_markup() -> None:
    payload = json.loads((ROOT / "news.json").read_text())
    item = parse_payload(payload)[0]
    raw = payload["data"][next(iter(payload["data"]))]["data"][0]

    assert item.content
    assert "<" not in item.content
    assert item.raw_json["content"] == raw["content"]
    assert item.raw_json["web_content"] == raw["web_content"]
    assert item.raw_json["content_pc"] == raw["content_pc"]


def test_leading_bracketed_title_is_extracted_from_content() -> None:
    payload = {
        "rslt": "succ",
        "data": {"day": {"data": [{
            "id": "1",
            "rec_time": "100",
            "content": "<b>original content</b>",
            "web_content": "【恒指跌0.73% 恒生科技指数跌0.76%】港股午间收盘，恒生指数跌0.7",
            "content_pc": "original PC content",
            "empty_text": "",
        }]}},
    }

    item = parse_payload(payload)[0]

    assert item.title == "恒指跌0.73% 恒生科技指数跌0.76%"
    assert item.content == "港股午间收盘，恒生指数跌0.7"
    assert item.raw_json["content"] == "<b>original content</b>"
    assert item.raw_json["web_content"].startswith("【恒指跌0.73%")
    assert item.raw_json["content_pc"] == "original PC content"
    assert "empty_text" not in item.raw_json


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("正文【不是标题】", (None, "正文【不是标题】")),
        ("【未闭合的标题", (None, "【未闭合的标题")),
        ("【】正文", (None, "【】正文")),
        ("【只有标题】", ("只有标题", None)),
    ],
)
def test_title_extraction_requires_nonempty_closed_prefix(
    content: str, expected: tuple[str | None, str | None]
) -> None:
    assert extract_title(content) == expected


def test_parser_flattens_all_date_groups() -> None:
    item = {"id": "1", "rec_time": "100", "stock_infos": []}
    payload = {
        "rslt": "succ",
        "data": {
            "today": {"data": [item]},
            "yesterday": {"data": [{**item, "id": "2", "rec_time": "90"}]},
        },
    }

    assert [news.id for news in parse_payload(payload)] == [1, 2]


def test_parser_deduplicates_relations() -> None:
    payload = {
        "rslt": "succ",
        "data": {"day": {"data": [{
            "id": "1",
            "rec_time": "100",
            "stock_infos": [
                {"kind": "stock", "code": "sz1", "name": "Old"},
                {"kind": "stock", "code": "sz1", "name": "New"},
                {"kind": "theme", "id": "7", "content": "Theme"},
                {"kind": "theme", "id": "7", "content": "Theme"},
            ],
        }]}},
    }

    news = parse_payload(payload)[0]

    assert news.stocks[0].name == "New"
    assert len(news.stocks) == len(news.themes) == 1


def test_parser_rejects_unsuccessful_payload() -> None:
    with pytest.raises(InvalidPayload):
        parse_payload({"rslt": "fail", "data": {}})
