"""1 fact_typeずつ独立してLLMへ問い、Test Case結果を作る。"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROMPT = Path(__file__).parent / "prompt.md"
MAX_TEXT_CHARS = 18000
MAX_LINKS = 40
# 渡すリンクの選び方。測定条件として記録する（並べ替えの有無で結果が変わる）
LINK_ORDER = "score_desc"
# 表の渡し方。測定条件として記録する（表読みの有無で結果が変わる）
TABLE_READING = "heading_value"
# 表テキストの上限。本文を削ってまで表を入れないための枠
MAX_TABLE_CHARS = 4000
MAX_FOLLOW = 2
# 読解に渡すページの決め方。測定条件として記録する。
#   agent_pick  AIが一覧から max_follow 本を選ぶ（いまのやり方）
#   strong_all  手続きに該当する候補を、こちらから全部渡す
# ★本数は max_follow が持っているので、ここには書かない（2箇所に書くとずれる）
READ_BREADTH = "agent_pick"
# HTML以外（PDF/Word/Excel）の扱い。測定条件として記録する。
#   none      弾く（2026-08-28 以前）
#   cmap_text 字形の対応表を使って本文を取り出す。読めなければ理由を残す
NON_HTML_READING = "cmap_text"

sys.path.insert(0, str(ROOT / "crawler"))
from discover import score_link  # noqa: E402
from htmlutil import Table, parse, tables_text  # noqa: E402
from officedoc import read_document  # noqa: E402
from polite_fetch import PoliteFetcher  # noqa: E402

sys.path.insert(0, str(ROOT))
from evidence_check import attach_checks_across_pages, truncate_page_text  # noqa: E402
from extractor.response_contract import (  # noqa: E402
    is_non_html_url,
    normalize_item,
    optional_text,
    parse_json_reply,
    requested_urls,
)
from fact_types import by_id  # noqa: E402
from failure_taxonomy import annotate_result  # noqa: E402
from measurement_cases import TestCase  # noqa: E402


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
        normalized.links, normalized.text, normalized.jsonld, extra_pages,
        tables=normalized.tables)


def table_section(text: str, tables: Sequence[Table]) -> str:
    """表を「見出し: 値」に直した節。本文と合わせて MAX_TEXT_CHARS を超えない分だけ返す。

    ★表のセルの文字は本文にも入っているが、どの見出しの列の値かは潰れている。
      見出しと値を組み直したものを別立てで渡す。

    本文を削ってまでは入れない。表が読めるようになった代わりに本文が消えると、
    どちらが効いたのか分からなくなるし、減った側の損は測りようがない。
    """
    room = min(MAX_TABLE_CHARS, MAX_TEXT_CHARS - min(len(text), MAX_TEXT_CHARS))
    return tables_text(tables)[:room] if room > 0 else ""


def compose_input(page: dict, muni: str, proc: str, test_case: TestCase,
                  links: list, text: str, jsonld: list[str],
                  extra_pages: list[tuple[str, str]] | None = None,
                  tables: Sequence[Table] = (),
                  ) -> tuple[str, dict, set[str]]:
    """解析済み内容から、本測定・再現実験で共通の1項目promptを作る。"""
    truncated = len(text) > MAX_TEXT_CHARS
    link_lines, allowed_urls = _prompt_links(links, keywords_for(proc))
    usable_jsonld = _usable_jsonld(jsonld)
    table_text = table_section(text, tables)
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
        _table_section_text(table_text),
        f"\n## このページから出ているリンク（最大{MAX_LINKS}件）\n\n"
        + ("\n".join(link_lines) or "（なし）"),
    ]
    parts.extend(_extra_page_sections(extra_pages or []))
    meta = {
        "has_jsonld": bool(usable_jsonld), "text_len": len(text),
        "truncated": truncated, "n_links": len(link_lines),
        "table_chars": len(table_text),
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
        # ★以前はここで「PDFを要求したら失敗」にしていた。読めなかった時代の名残。
        #   いまは読めるので、要求されたら開く。読めなければ理由を残して添付に落とす。
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
    """開いてみたが読めなかった添付。**読まなかったのではない。**

    ★以前は「添付ファイルのため本文を開かなかった」と書いていた。
      いまは開く。ここに来るのは**開いた上で読めなかった**もの（画像PDF等）だけで、
      `urls` には理由が付いている。
    """
    return {
        "stage": "follow_fetch",
        "llm_called": False,
        "result": {
            "found": False, "value": "", "evidence": "", "source": None,
            "failure_reason": "PDF内のみ",
        },
        "requested_urls": [],
        "attachment_urls": urls,
        "page_notes": "添付を開いたが本文を取り出せなかった（理由はURLに併記）",
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


_TARGETS: dict | None = None


def _targets() -> dict:
    """targets.json を1度だけ読む。並べ替えのたびに開かない。"""
    global _TARGETS
    if _TARGETS is None:
        _TARGETS = json.loads(
            (ROOT / "crawler" / "targets.json").read_text(encoding="utf-8"))
    return _TARGETS


def keywords_for(proc_name: str) -> dict | None:
    """手続き名からキーワードを引く。並べ替えの点は discover と同じものを使う。"""
    for p in _targets().get("procedures", []):
        if p.get("name") == proc_name:
            return p.get("keywords")
    return None


def _prompt_links(links: list, kw: dict | None = None) -> tuple[list[str], set[str]]:
    """AIに渡すリンク一覧。

    ★ページに出てきた順で MAX_LINKS 件で打ち切ると、地域ナビゲーションや
      共通メニューで埋まって本命が入らない。68セルの観察記録のうち
      30セルが「答えはリンクの先にあるのに、そのURLを渡していない」だった。

    手続きページらしい順に並べ替えてから打ち切る。点の付け方は
    `crawler/discover.py` の `score_link` と同じで、ここで新しく点は作らない。
    同点はページに出てきた順を保つ（安定ソート）。
    """
    seen, uniq = set(), []
    for link in links:
        if not link.text or link.href in seen:
            continue
        seen.add(link.href)
        uniq.append(link)
    if kw:
        uniq.sort(key=lambda link: -score_link(link.text, link.href, kw))
    picked = uniq[:MAX_LINKS]
    return ([f"- {link.text} → {link.href}" for link in picked],
            {link.href for link in picked})


def _table_section_text(table_text: str) -> str:
    """表が無いページには節ごと足さない。空の見出しは入力の無駄にしかならない。"""
    if not table_text:
        return ""
    return ("\n## このページの表（行ごとに「見出し: 値」へ組み直したもの）\n\n"
            "（本文にも同じ文字が入っていますが、そこでは列の対応が潰れています）\n\n"
            f"{table_text}\n")


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
        # ★プロンプトに足した「記載なしにする前に必ずリンクを入れる」規則が、
        #   この2回目にも効いてしまい `follow_urlsは最大0件: 1件ある` で落ちた
        #   （粗大ごみ・実測）。節を立てて明示的に打ち消す。
        sections.append(
            "\n---\n\n## ここで終わりです（上の探索順序より優先）\n\n"
            "上のリンク先ページはあなたの要求で開いたものです。ここから答えが"
            "取れた項目は found=true / source=\"linked_page\" とし、"
            "failure_reason は null にしてください。\n\n"
            "**リンク追従はここで終了します。追加のリンクは開けません。**\n"
            "ここにも無ければ `記載なし` としてください。\n"
            "**`follow_urls` は必ず空配列 `[]` にしてください。**\n"
            "「`記載なし` にする前にリンクを入れる」規則は、ここでは適用しません。\n")
    return sections


def _fetch_followed_urls(urls: list[str], fetcher: PoliteFetcher,
                         ) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """要求されたリンクを開く。**添付も読めるなら読む。**

    ★以前は非HTMLを一律で `attachments` に落とし、`failure_reason: PDF内のみ` で
      終わらせていた。だが住民のAI（ChatGPT / Claude）はPDFを読む。
      読めなかったのはこちらの読み取り器だけで、**区の落ち度ではなく
      こちらの落ち度を測っていた**（plans/decisions/non-html-reading.md）。

      いまは字形の対応表を使って読める（PDF 6/7）。読めたものは本文として渡し、
      読めなかったものだけを添付として残す。**読めない理由も一緒に残す。**
    """
    followed, extra, attachments = [], [], []
    for url in urls[:MAX_FOLLOW]:
        fetched = fetcher.fetch(url)
        if not fetched.body_path:
            continue
        if _fetched_non_html(fetched, url):
            got = read_document(fetched.body_bytes(), url,
                                getattr(fetched, "content_type", "") or "")
            if got.ok:
                followed.append(url)
                extra.append((f"{url}（{got.kind}）", got.text))
            else:
                attachments.append(f"{url}（{got.reason}）")
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
    normalized = parse(cached.body(), page["url"])
    page_texts = [truncate_page_text(normalized.text)]
    # 組み直した表も「渡した文」なので照合対象に入れる。入れないと、
    # 表から正しく引いた根拠が捏造の疑い（missing）に落ちる。
    table_text = table_section(normalized.text, normalized.tables)
    if table_text:
        page_texts.append(table_text)
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
