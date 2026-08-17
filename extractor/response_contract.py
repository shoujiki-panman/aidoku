"""1 fact_typeぶんのLLM応答を厳密に検証する。"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from failure_taxonomy import annotate_result

VALID_SOURCES = frozenset({"html", "jsonld", "linked_page"})
VALID_FAILURE_REASONS = frozenset({
    "PDF内のみ", "リンク先にあり", "電話でのみ確認可", "記載なし", "曖昧",
})
NON_HTML_SUFFIXES = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rtf", ".odt", ".ods", ".csv",
)


def parse_json_reply(raw: str) -> dict:
    """コードフェンスや前置きが付いていてもJSON objectを取り出す。"""
    if not isinstance(raw, str):
        raise ValueError("LLM応答が文字列でない")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSONが見つからない: {raw[:300]}")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("LLM応答のrootがobjectでない")
    return data


def normalize_item(data: dict,
                   allowed_sources: frozenset[str] = VALID_SOURCES) -> dict:
    """1 Test Caseの応答を、既存itemsの1項目と同じ形へ正規化する。"""
    item = data.get("item")
    if not isinstance(item, dict):
        raise ValueError("itemがobjectでない")
    if type(item.get("found")) is not bool:
        raise ValueError("item.foundがbooleanでない")
    normalized = {
        "found": item["found"],
        "value": optional_text(item, "value"),
        "evidence": optional_text(item, "evidence"),
        "source": optional_text(item, "source") or None,
        "failure_reason": optional_text(item, "failure_reason") or None,
    }
    _validate_item_state(normalized, allowed_sources)
    return annotate_result(normalized)


def requested_urls(data: dict, allowed_urls: set[str],
                   max_urls: int | None = None) -> list[str]:
    """follow_urlsを検証し、promptに提示済みのHTTP(S)リンクだけを返す。"""
    urls = data.get("follow_urls", [])
    if not isinstance(urls, list):
        raise ValueError("follow_urlsが配列でない")
    out = []
    for url in urls:
        if not isinstance(url, str) or not _valid_http_url(url):
            raise ValueError(f"follow_urlsに正しいHTTP(S) URLでない値がある: {url!r}")
        if url not in allowed_urls:
            raise ValueError(f"follow_urlsに提示していないURLがある: {url}")
        if url not in out:
            out.append(url)
    if max_urls is not None and len(out) > max_urls:
        raise ValueError(f"follow_urlsは最大{max_urls}件: {len(out)}件ある")
    return out


def optional_text(data: dict, key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key}が文字列でない")
    return value.strip()


def is_non_html_url(url: str) -> bool:
    """URL pathがPDF/Office等の添付ファイルを指しているか。"""
    return urlsplit(url).path.lower().endswith(NON_HTML_SUFFIXES)


def _validate_item_state(item: dict, allowed_sources: frozenset[str]) -> None:
    if item["source"] is not None and item["source"] not in VALID_SOURCES:
        raise ValueError(f"item.sourceが不正: {item['source']}")
    if item["found"]:
        if not item["value"] or not item["evidence"] or item["source"] is None:
            raise ValueError("found=trueにはvalue/evidence/sourceが必要")
        if item["failure_reason"] is not None:
            raise ValueError("found=trueでfailure_reasonが設定されている")
        if item["source"] not in allowed_sources:
            raise ValueError(f"この入力に含まれないsourceが設定されている: {item['source']}")
    else:
        if item["source"] is not None:
            raise ValueError("found=falseでsourceが設定されている")
        if item["failure_reason"] is None:
            raise ValueError("found=falseにはfailure_reasonが必要")
        if item["value"] or item["evidence"]:
            raise ValueError("found=falseではvalue/evidenceを空にする")
        if item["failure_reason"] not in VALID_FAILURE_REASONS:
            raise ValueError(f"failure_reasonが不正: {item['failure_reason']}")


def _valid_http_url(url: str) -> bool:
    if any(char.isspace() or ord(char) < 32 for char in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    try:
        hostname = parts.hostname
        _ = parts.port  # 参照した時点で不正なポートは ValueError になる（これが検査）
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(hostname)
