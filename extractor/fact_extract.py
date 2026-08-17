"""1 fact_typeずつ独立してLLMへ問い、Test Case結果を作る。"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROMPT = Path(__file__).parent / "prompt.md"
MAX_TEXT_CHARS = 18000
MAX_LINKS = 40
MAX_FOLLOW = 2

sys.path.insert(0, str(ROOT / "crawler"))
from htmlutil import parse  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

sys.path.insert(0, str(ROOT))
from evidence_check import attach_checks_across_pages, truncate_page_text  # noqa: E402
from fact_types import by_id  # noqa: E402
from failure_taxonomy import annotate_result  # noqa: E402
from measurement_cases import TestCase  # noqa: E402

from extractor.response_contract import (  # noqa: E402
    is_non_html_url, normalize_item, optional_text, parse_json_reply, requested_urls,
)


def build_input(page: dict, muni: str, proc: str, test_case: TestCase,
                fetcher: PoliteFetcher,
                extra_pages: list[tuple[str, str]] | None = None,
                ) -> tuple[str, dict, set[str]]:
    result = fetcher.cached(page["url"])
    if result is None or not result.body_path:
        raise RuntimeError(
            f"キャッシュに無い: {page['url']}（先に crawler/discover.py を実行）")
    normalized = parse(result.body(), page["url"])
    return compose_input(
        page, muni, proc, test_case,
        normalized.links, normalized.text, normalized.jsonld, extra_pages)


def compose_input(page: dict, muni: str, proc: str, test_case: TestCase,
                  links: list, text: str, jsonld: list[str],
                  extra_pages: list[tuple[str, str]] | None = None,
                  ) -> tuple[str, dict, set[str]]:
    """解析済み内容から、本測定・再現実験で共通の1項目promptを作る。"""
    truncated = len(text) > MAX_TEXT_CHARS
    link_lines, allowed_urls = _prompt_links(links)
    usable_jsonld = _usable_jsonld(jsonld)
    fact = by_id(test_case.fact_type)
    parts = [
        PROMPT.read_text(encoding="utf-8"),
        "\n---\n",
        "## Test Case\n\n",
        f"- service: {test_case.service}\n",
        f"- fact_type: {test_case.fact_type}\n",
        f"- test_case_version: {test_case.test_case_version}\n",
        f"- 質問: {test_case.question}\n",
        f"- 出力対象: {fact['extractor_key']}\n",
        "\nこの1項目だけを判定し、他のfact_typeは答えないでください。\n",
        f"## 対象\n\n- 自治体: {muni}\n- 手続き: {proc}\n- ページURL: {page['url']}\n",
        _jsonld_section(usable_jsonld),
        f"\n## ページ本文{'（長いため冒頭のみ）' if truncated else ''}\n\n"
        f"{text[:MAX_TEXT_CHARS]}\n",
        f"\n## このページから出ているリンク（最大{MAX_LINKS}件）\n\n"
        + ("\n".join(link_lines) or "（なし）"),
    ]
    parts.extend(_extra_page_sections(extra_pages or []))
    meta = {
        "has_jsonld": bool(usable_jsonld), "text_len": len(text),
        "truncated": truncated, "n_links": len(link_lines),
    }
    return "".join(parts), meta, allowed_urls


def call_claude(prompt: str, model: str, timeout: int = 300) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p failed (rc={proc.returncode}): {proc.stderr[:500]}")
    return proc.stdout


def run_test_case(page: dict, muni: str, proc: str, test_case: TestCase,
                  fetcher: PoliteFetcher, model: str,
                  follow: bool) -> tuple[dict, dict, list[tuple[str, str]]]:
    """1 fact_typeだけを呼び、要求されたリンクもこのTest Caseだけで読む。"""
    try:
        prompt, meta, allowed_urls = build_input(
            page, muni, proc, test_case, fetcher)
        data = parse_json_reply(call_claude(prompt, model))
        urls = requested_urls(data, allowed_urls, MAX_FOLLOW)
        if any(is_non_html_url(url) for url in urls):
            raise ValueError(
                "PDF/Office等の添付はfollow_urlsにせずfailure_reason=PDF内のみにする")
        attempts = [validated_attempt(
            data, allowed_sources(meta), "initial", urls)]
        followed, extra, attachments = (
            _fetch_followed_urls(urls, fetcher) if follow else ([], [], []))
        if attachments:
            attempts.append(_attachment_observation(attachments))
        if extra:
            retry_prompt, _, retry_allowed = build_input(
                page, muni, proc, test_case, fetcher, extra_pages=extra)
            data = parse_json_reply(call_claude(retry_prompt, model))
            retry_urls = requested_urls(data, retry_allowed, 0)
            attempts.append(validated_attempt(
                data, allowed_sources(meta, linked=True),
                "follow", retry_urls))
        evidence_summary = _attach_evidence_check(
            page, fetcher, extra, attempts[-1])
        record = {
            **asdict(test_case),
            "result": attempts[-1]["result"],
            "attempts": attempts,
            "followed_urls": followed,
            "page_notes": attempts[-1]["page_notes"],
            "evidence_summary": evidence_summary,
        }
        return record, meta, extra
    except Exception as exc:
        raise RuntimeError(
            f"Test Case失敗: {test_case.service}/{test_case.fact_type}: {exc}") from exc


def validated_attempt(data: dict, sources: frozenset[str],
                      stage: str, urls: list[str]) -> dict:
    result = normalize_item(data, sources)
    is_follow_request = (
        not result["found"] and result["failure_reason"] == "リンク先にあり")
    if stage == "initial" and bool(urls) != is_follow_request:
        raise ValueError(
            "初回のリンク先にあり判定とfollow_urlsの有無を一致させる")
    return {
        "stage": stage,
        "llm_called": True,
        "result": result,
        "requested_urls": urls,
        "page_notes": optional_text(data, "page_notes"),
    }


def allowed_sources(meta: dict, linked: bool = False) -> frozenset[str]:
    sources = {"html"}
    if meta["has_jsonld"]:
        sources.add("jsonld")
    if linked:
        sources.add("linked_page")
    return frozenset(sources)


def _attachment_observation(urls: list[str]) -> dict:
    return {
        "stage": "follow_fetch",
        "llm_called": False,
        "result": {
            "found": False, "value": "", "evidence": "", "source": None,
            "evidence_location": None, "confidence": None,
            "failure_reason": "PDF内のみ",
        },
        "requested_urls": [],
        "attachment_urls": urls,
        "page_notes": "添付ファイルのため本文を開かなかった",
    }


def run_test_cases(page: dict, muni: str, proc: str, cases: list[TestCase],
                   fetcher: PoliteFetcher, model: str,
                   follow: bool) -> tuple[list[dict], dict, list[tuple[str, str]]]:
    """Test Caseを混ぜずに実行し、clarityへ渡すリンク先だけ重複を畳む。"""
    if not cases:
        raise ValueError("Test Caseが0件")
    records = []
    page_meta: dict | None = None
    extra_by_url: dict[str, str] = {}
    for test_case in cases:
        record, meta, extra = run_test_case(
            page, muni, proc, test_case, fetcher, model, follow)
        records.append(record)
        page_meta = page_meta or meta
        for url, text in extra:
            extra_by_url.setdefault(url, text)
    return records, page_meta or {}, list(extra_by_url.items())


def _prompt_links(links: list) -> tuple[list[str], set[str]]:
    lines, allowed_urls = [], set()
    for link in links:
        if not link.text or link.href in allowed_urls:
            continue
        allowed_urls.add(link.href)
        lines.append(f"- {link.text} → {link.href}")
        if len(lines) >= MAX_LINKS:
            break
    return lines, allowed_urls


def _jsonld_section(jsonld: list[str]) -> str:
    content = "（なし）" if not jsonld else "\n".join(jsonld)[:2000]
    return f"\n## 構造化データ (JSON-LD)\n\n{content}\n"


def _usable_jsonld(jsonld: list[str]) -> list[str]:
    if not isinstance(jsonld, list) or any(
            not isinstance(block, str) for block in jsonld):
        raise ValueError("jsonldは文字列の配列にする")
    return [block for block in jsonld if block.strip()]


def _extra_page_sections(pages: list[tuple[str, str]]) -> list[str]:
    sections = [
        f"\n---\n\n## リンク先ページの本文（{url}）\n\n{text[:MAX_TEXT_CHARS]}\n"
        for url, text in pages
    ]
    if pages:
        sections.append(
            "\n（上のリンク先ページはあなたの要求で開いたものです。ここから答えが"
            "取れた項目はfound=true / source=\"linked_page\"とし、"
            "failure_reasonはnullにしてください。リンク追従はここで終了するため、"
            "follow_urlsは空配列にしてください。）")
    return sections


def _fetch_followed_urls(urls: list[str], fetcher: PoliteFetcher,
                         ) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    followed, extra, attachments = [], [], []
    for url in urls[:MAX_FOLLOW]:
        fetched = fetcher.fetch(url)
        if not fetched.body_path:
            continue
        if _fetched_non_html(fetched, url):
            attachments.append(url)
            continue
        page_text = parse(fetched.body(), url).text
        followed.append(url)
        extra.append((url, page_text))
    return followed, extra, attachments


def _attach_evidence_check(page: dict, fetcher: PoliteFetcher,
                           extra: list[tuple[str, str]], attempt: dict) -> dict:
    """最終attemptの引用を、そのTest Caseが実際に読んだページだけで照合する。"""
    cached = fetcher.cached(page["url"])
    if cached is None or not cached.body_path:
        raise RuntimeError(f"照合対象のキャッシュが無い: {page['url']}")
    page_texts = [truncate_page_text(parse(cached.body(), page["url"]).text)]
    page_texts.extend(truncate_page_text(text) for _url, text in extra)
    checked, summary = attach_checks_across_pages(
        {"item": attempt["result"]}, page_texts)
    attempt["result"] = annotate_result(checked["item"])
    return summary


def _fetched_non_html(fetched: object, requested_url: str) -> bool:
    final_url = getattr(fetched, "final_url", requested_url) or requested_url
    content_type = (getattr(fetched, "content_type", "") or "")
    if is_non_html_url(final_url):
        return True
    if not content_type.strip():
        return False
    mime = content_type.split(";", 1)[0].strip().lower()
    return mime not in {"text/html", "application/xhtml+xml"}
